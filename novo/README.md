# Empreende Tec

Vitrine de produtos e serviços dos alunos do Senac. Flask + SQLite.

## Requisitos da atividade
- **SQLite com tabelas relacionadas**: `usuarios` 1—N `produtos` N—1 `categorias` (chaves estrangeiras, `ON DELETE CASCADE`).
- **CRUD completo**: anúncios (`/novo_produto`, `/produto/<id>`, `/editar/<id>`, `/excluir/<id>`) e usuários (`/cadastro`, `/perfil`, `/perfil/editar`, `/perfil/excluir`).
- **API JSON**: `GET /api/produtos` (filtros `?q=`, `?tipo=Produto|Serviço`, `?categoria=<id>`) e `GET /api/produtos/<id>`.

## Rodar local
```
pip install -r requirements.txt
python app.py
```
Na primeira execução o banco SQLite `empreendetec.db` é criado com as tabelas e as categorias: Doces, Bebidas, Lanches, Artesanato, Roupas, Materiais, Serviços e Outros. Todos os dados ficam no banco (não há mais arquivos JSON).

## Publicar no Render
1. Suba a pasta para um repositório no GitHub.
2. Render → New → Web Service → escolha o repositório (ou New → Blueprint, que usa o `render.yaml`).
3. Build Command: `pip install -r requirements.txt` · Start Command: `gunicorn app:app`
4. Environment: `SECRET_KEY` = qualquer texto longo; `PYTHON_VERSION` = `3.12.3`.

Atenção: no plano gratuito o disco é temporário. O banco e as imagens enviadas voltam ao estado inicial (apenas as categorias) quando o serviço reinicia ou é publicado de novo. Para a apresentação, cadastre os dados de demonstração pouco antes. Para persistir, use um Persistent Disk (plano pago) montado em `/var/data` e defina `DATA_DIR=/var/data`.
