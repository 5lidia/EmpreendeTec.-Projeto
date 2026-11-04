import os, sqlite3, time
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   session, send_from_directory, jsonify, g)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', BASE))      # no Render com disco: DATA_DIR=/var/data
DB = DATA_DIR / 'empreendetec.db'
UPLOADS = DATA_DIR / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
TIPOS = ('Produto', 'Serviço')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'troque-esta-chave-em-producao')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.json.ensure_ascii = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, turma TEXT NOT NULL,
  email TEXT NOT NULL, telefone TEXT NOT NULL,
  usuario TEXT NOT NULL UNIQUE COLLATE NOCASE, senha TEXT NOT NULL,
  foto TEXT DEFAULT '', loja TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS categorias(
  id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE, icone TEXT);
CREATE TABLE IF NOT EXISTS produtos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id),
  tipo TEXT NOT NULL DEFAULT 'Produto', nome TEXT NOT NULL, descricao TEXT NOT NULL,
  preco REAL NOT NULL, quantidade INTEGER NOT NULL, pagamento TEXT NOT NULL,
  local_entrega TEXT NOT NULL, whatsapp TEXT NOT NULL, imagem TEXT DEFAULT '',
  views INTEGER DEFAULT 0, created_at TEXT, status TEXT DEFAULT 'Disponível');
CREATE TABLE IF NOT EXISTS interessados(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
  nome TEXT NOT NULL, email TEXT NOT NULL, telefone TEXT NOT NULL,
  quantidade INTEGER NOT NULL DEFAULT 1, mensagem TEXT DEFAULT '', created_at TEXT);
'''
CATEGORIAS = [('Doces', '🍰'), ('Bebidas', '🥤'), ('Lanches', '🥪'), ('Artesanato', '🎨'),
              ('Roupas', '👕'), ('Materiais', '📦'), ('Serviços', '🛠️'), ('Outros', '🛍️')]


def conectar():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def db():
    if 'db' not in g:
        g.db = conectar()
    return g.db


@app.teardown_appcontext
def fechar(_):
    c = g.pop('db', None)
    if c:
        c.close()


def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur.lastrowid


def init_db():
    """Cria as tabelas no banco SQLite (empreendetec.db) e as categorias padrão. Sem arquivos JSON."""
    c = conectar()
    c.executescript(SCHEMA)
    for nome, icone in CATEGORIAS:
        c.execute('INSERT OR IGNORE INTO categorias(nome,icone) VALUES(?,?)', (nome, icone))
    c.commit()
    c.close()


init_db()


# ---------- utilidades ----------
def salvar_img(f, prefixo):
    if f and f.filename and '.' in f.filename and f.filename.rsplit('.', 1)[1].lower() in EXT:
        nome = secure_filename(f'{prefixo}_{int(time.time())}_{f.filename}')
        f.save(UPLOADS / nome)
        return nome
    return None


def status(qtd):
    return 'Disponível' if qtd > 0 else 'Esgotado'


@app.before_request
def carregar_usuario():
    uid = session.get('user_id')
    g.user = q('SELECT * FROM usuarios WHERE id=?', (uid,), True) if uid else None


@app.context_processor
def contexto():
    return dict(user=g.get('user'), categorias=q('SELECT * FROM categorias ORDER BY id'), TIPOS=TIPOS)


@app.template_filter('brl')
def brl(v):
    return 'R$ ' + f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


@app.template_filter('digitos')
def digitos(v):
    return ''.join(ch for ch in v or '' if ch.isdigit())


def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not g.user:
            flash('Faça login para acessar essa página.', 'warning')
            return redirect(url_for('login'))
        return fn(*a, **k)
    return w


SEL = '''SELECT p.*, c.nome AS categoria, c.icone, u.nome AS vendedor, u.loja
         FROM produtos p JOIN categorias c ON c.id=p.categoria_id JOIN usuarios u ON u.id=p.usuario_id'''


def buscar(args, so_disponiveis=False, limite=None):
    w, a = [], []
    if so_disponiveis:
        w.append("p.status='Disponível'")
    if args.get('q'):
        w.append('(p.nome LIKE ? OR p.descricao LIKE ?)')
        a += [f"%{args['q']}%"] * 2
    if args.get('tipo') in TIPOS:
        w.append('p.tipo=?'); a.append(args['tipo'])
    if str(args.get('categoria', '')).isdigit():
        w.append('p.categoria_id=?'); a.append(int(args['categoria']))
    sql = SEL + (' WHERE ' + ' AND '.join(w) if w else '') + ' ORDER BY p.id DESC'
    if limite:
        sql += f' LIMIT {int(limite)}'
    return q(sql, a)


def ler_produto():
    d = {k: request.form.get(k, '').strip() for k in
         ('nome', 'tipo', 'categoria_id', 'descricao', 'preco', 'quantidade', 'pagamento', 'local_entrega', 'whatsapp')}
    if not all(d.values()) or d['tipo'] not in TIPOS:
        return None
    try:
        d['preco'] = float(d['preco'].replace(',', '.'))
        d['quantidade'] = int(d['quantidade'])
        d['categoria_id'] = int(d['categoria_id'])
    except ValueError:
        return None
    if d['preco'] < 0 or d['quantidade'] < 0 or not q('SELECT 1 FROM categorias WHERE id=?', (d['categoria_id'],)):
        return None
    d['status'] = status(d['quantidade'])
    return d


# ---------- páginas públicas ----------
@app.route('/')
def index():
    return render_template('index.html', destaques=buscar({}))  # todos os anúncios cadastrados


@app.route('/produtos')
def produtos():
    f = {k: request.args.get(k, '').strip() for k in ('q', 'tipo', 'categoria')}
    return render_template('produtos.html', items=buscar(f), f=f)


@app.route('/produto/<int:produto_id>')
def produto(produto_id):
    p = q(SEL + ' WHERE p.id=?', (produto_id,), True)
    if not p:
        return render_template('404.html'), 404
    run('UPDATE produtos SET views=views+1 WHERE id=?', (produto_id,))
    vendedor = q('SELECT * FROM usuarios WHERE id=?', (p['usuario_id'],), True)
    return render_template('produto.html', p=p, vendedor=vendedor, f={})


@app.route('/produto/<int:produto_id>/interesse', methods=['POST'])
def interesse(produto_id):
    p = q('SELECT id FROM produtos WHERE id=?', (produto_id,), True)
    if not p:
        return render_template('404.html'), 404
    f = {k: request.form.get(k, '').strip()[:500] for k in ('nome', 'email', 'telefone', 'quantidade', 'mensagem')}
    try:
        qtd = max(1, int(f['quantidade'] or 1))
    except ValueError:
        qtd = 1
    if not (f['nome'] and '@' in f['email'] and len(digitos(f['telefone'])) >= 8):
        flash('Preencha nome, e-mail e telefone válidos.', 'warning')
    else:
        run('INSERT INTO interessados(produto_id,nome,email,telefone,quantidade,mensagem,created_at) VALUES(?,?,?,?,?,?,?)',
            (produto_id, f['nome'], f['email'], f['telefone'], qtd, f['mensagem'], datetime.now().strftime('%d/%m/%Y %H:%M')))
        flash('Cadastro enviado! O vendedor vai entrar em contato com você.', 'success')
    return redirect(url_for('produto', produto_id=produto_id) + '#comprar')


@app.route('/sobre')
def sobre():
    return render_template('sobre.html')


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOADS, filename)


# ---------- API JSON ----------
def p_json(r):
    d = dict(r)
    d['imagem_url'] = request.host_url.rstrip('/') + url_for('uploaded_file', filename=r['imagem']) if r['imagem'] else None
    return d


@app.route('/api/produtos')
def api_produtos():
    """Filtros opcionais: ?q=texto&tipo=Produto|Serviço&categoria=<id>"""
    rows = buscar(request.args, so_disponiveis=request.args.get('todos') != '1')
    return jsonify(total=len(rows), produtos=[p_json(r) for r in rows])


@app.route('/api/produtos/<int:produto_id>')
def api_produto(produto_id):
    r = q(SEL + ' WHERE p.id=?', (produto_id,), True)
    return (jsonify(p_json(r)) if r else (jsonify(erro='Produto não encontrado'), 404))


# ---------- contas (CRUD de usuários) ----------
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if g.user:
        return redirect(url_for('painel'))
    if request.method == 'POST':
        f = {k: request.form.get(k, '').strip() for k in
             ('nome', 'turma', 'email', 'telefone', 'usuario', 'senha', 'confirmar_senha', 'loja')}
        obrig = [f[k] for k in ('nome', 'turma', 'email', 'telefone', 'usuario', 'senha', 'confirmar_senha')]
        if not all(obrig):
            flash('Preencha todos os campos obrigatórios.', 'warning')
        elif f['senha'] != f['confirmar_senha']:
            flash('As senhas não coincidem.', 'warning')
        elif q('SELECT 1 FROM usuarios WHERE usuario=?', (f['usuario'],)):
            flash('Já existe um usuário com esse login.', 'warning')
        else:
            foto = salvar_img(request.files.get('foto'), 'u') or ''
            run('INSERT INTO usuarios(nome,turma,email,telefone,usuario,senha,foto,loja) VALUES(?,?,?,?,?,?,?,?)',
                (f['nome'], f['turma'], f['email'], f['telefone'], f['usuario'],
                 generate_password_hash(f['senha']), foto, f['loja']))
            flash('Cadastro realizado! Faça login para continuar.', 'success')
            return redirect(url_for('login'))
        return render_template('cadastro.html', f=f)
    return render_template('cadastro.html', f={})


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('painel'))
    if request.method == 'POST':
        ident, senha = request.form.get('usuario', '').strip(), request.form.get('senha', '')
        u = q('SELECT * FROM usuarios WHERE usuario=? OR lower(email)=lower(?)', (ident, ident), True)
        if u and check_password_hash(u['senha'], senha):
            session['user_id'] = u['id']
            flash(f'Olá, {u["nome"]}! Bem-vindo ao seu painel.', 'success')
            return redirect(url_for('painel'))
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))


@app.route('/perfil')
@login_required
def perfil():
    n = q('SELECT COUNT(*) n FROM produtos WHERE usuario_id=?', (g.user['id'],), True)['n']
    return render_template('perfil.html', total=n)


@app.route('/perfil/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil():
    if request.method == 'POST':
        f = {k: request.form.get(k, '').strip() for k in
             ('nome', 'turma', 'email', 'telefone', 'usuario', 'loja', 'senha', 'confirmar_senha')}
        if not all(f[k] for k in ('nome', 'turma', 'email', 'telefone', 'usuario')):
            flash('Preencha todos os campos obrigatórios.', 'warning')
        elif q('SELECT 1 FROM usuarios WHERE usuario=? AND id<>?', (f['usuario'], g.user['id'])):
            flash('Já existe um usuário com esse login.', 'warning')
        elif f['senha'] != f['confirmar_senha']:
            flash('As senhas não coincidem.', 'warning')
        else:
            senha = generate_password_hash(f['senha']) if f['senha'] else g.user['senha']
            foto = salvar_img(request.files.get('foto'), 'u') or g.user['foto']
            run('UPDATE usuarios SET nome=?,turma=?,email=?,telefone=?,usuario=?,loja=?,senha=?,foto=? WHERE id=?',
                (f['nome'], f['turma'], f['email'], f['telefone'], f['usuario'], f['loja'], senha, foto, g.user['id']))
            flash('Perfil atualizado.', 'success')
            return redirect(url_for('perfil'))
    return render_template('editar_perfil.html')


@app.route('/perfil/excluir', methods=['POST'])
@login_required
def excluir_conta():
    run('DELETE FROM usuarios WHERE id=?', (g.user['id'],))   # apaga também os anúncios (ON DELETE CASCADE)
    session.clear()
    flash('Sua conta e seus anúncios foram excluídos.', 'success')
    return redirect(url_for('index'))


# ---------- anúncios (CRUD de produtos/serviços) ----------
@app.route('/painel')
@login_required
def painel():
    itens = q(SEL + ' WHERE p.usuario_id=? ORDER BY p.id DESC', (g.user['id'],))
    pedidos = q('''SELECT i.*, p.nome AS produto FROM interessados i JOIN produtos p ON p.id=i.produto_id
                   WHERE p.usuario_id=? ORDER BY i.id DESC''', (g.user['id'],))
    return render_template('painel.html', itens=itens, pedidos=pedidos, views=sum(i['views'] for i in itens),
                           esgotados=sum(1 for i in itens if i['status'] == 'Esgotado'))


@app.route('/meus_produtos')
@login_required
def meus_produtos():
    return redirect(url_for('painel'))


@app.route('/novo_produto', methods=['GET', 'POST'])
@login_required
def novo_produto():
    if request.method == 'POST':
        d = ler_produto()
        if not d:
            flash('Preencha todos os campos corretamente.', 'warning')
            return redirect(url_for('novo_produto'))
        d.update(uid=g.user['id'], imagem=salvar_img(request.files.get('imagem'), 'p') or '',
                 criado=datetime.now().strftime('%d/%m/%Y'))
        run('''INSERT INTO produtos(usuario_id,categoria_id,tipo,nome,descricao,preco,quantidade,pagamento,
               local_entrega,whatsapp,imagem,created_at,status) VALUES(:uid,:categoria_id,:tipo,:nome,:descricao,
               :preco,:quantidade,:pagamento,:local_entrega,:whatsapp,:imagem,:criado,:status)''', d)
        flash('Anúncio publicado.', 'success')
        return redirect(url_for('painel'))
    return render_template('form_produto.html', p={})


@app.route('/editar/<int:produto_id>', methods=['GET', 'POST'])
@login_required
def editar(produto_id):
    p = q('SELECT * FROM produtos WHERE id=? AND usuario_id=?', (produto_id, g.user['id']), True)
    if not p:
        flash('Anúncio não encontrado.', 'danger')
        return redirect(url_for('painel'))
    if request.method == 'POST':
        d = ler_produto()
        if not d:
            flash('Preencha todos os campos corretamente.', 'warning')
            return redirect(url_for('editar', produto_id=produto_id))
        d.update(id=produto_id, uid=g.user['id'], imagem=salvar_img(request.files.get('imagem'), 'p'))
        run('''UPDATE produtos SET categoria_id=:categoria_id,tipo=:tipo,nome=:nome,descricao=:descricao,
               preco=:preco,quantidade=:quantidade,pagamento=:pagamento,local_entrega=:local_entrega,
               whatsapp=:whatsapp,status=:status,imagem=COALESCE(:imagem,imagem)
               WHERE id=:id AND usuario_id=:uid''', d)
        flash('Anúncio atualizado.', 'success')
        return redirect(url_for('painel'))
    return render_template('form_produto.html', p=p)


@app.route('/excluir/<int:produto_id>', methods=['POST'])
@login_required
def excluir(produto_id):
    run('DELETE FROM produtos WHERE id=? AND usuario_id=?', (produto_id, g.user['id']))
    flash('Anúncio excluído.', 'success')
    return redirect(url_for('painel'))


@app.errorhandler(404)
def nao_achou(_):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(debug=True)
