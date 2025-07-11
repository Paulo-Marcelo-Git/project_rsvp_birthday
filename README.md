# Comemore+ 🎉  
Sistema de RSVP para convites de aniversário

Este é um projeto web simples desenvolvido com **Flask**, **MySQL** e **Docker**, que permite o envio de convites personalizados e o acompanhamento das respostas dos convidados (Sim / Não). Ideal para organizar festas e eventos!

---

## ✨ Funcionalidades

- Envio de convites personalizados com link único
- Página pública de confirmação (Sim / Não)
- Painel administrativo protegido por login
- Estatísticas em tempo real das respostas
- Botão de envio direto por WhatsApp
- Customização de textos do convite
- Layout responsivo e visual moderno

---

## 📦 Estrutura do Projeto

```
project_rsvp_birthday/
│
├── backend/
│   ├── app.py               # Aplicação principal Flask
│   ├── Dockerfile           # Imagem do backend
│   ├── init.sql             # Script para inicializar o banco MySQL
│   ├── requirements.txt     # Dependências Python
│   ├── static/
│   │   ├── admin.css        # Estilo do painel admin
│   │   └── antonio.jpg      # Imagem do aniversariante
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── invite.html
│       └── admin_responses.html
│
├── .env                     # Variáveis de ambiente (não versionado)
├── .gitignore
└── docker-compose.yml       # Orquestração com Docker
```

---

## 🚀 Como Executar

### 1. Pré-requisitos

- Docker + Docker Compose instalados

### 2. Configurar variáveis de ambiente

Crie um arquivo `.env` na raiz com o seguinte conteúdo:

```
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=sua_senha_mysql
DB_HOST=db

ADMIN_USER=admin
ADMIN_PASS=sua_senha_admin

SECRET_KEY=chave_secreta_flask
```

### 3. Subir os containers

```bash
docker-compose up --build
```

- Acesse o **painel admin** em: [http://localhost:3000/login](http://localhost:3000/login)
- Acesse os **convites** pelos links gerados (ex: http://localhost:3000/invite/...)

---

## 🛠️ Acesso Padrão

- Usuário: `admin`
- Senha: definida na variável `ADMIN_PASS`

---

## 🗃️ Banco de Dados

As tabelas são criadas automaticamente no primeiro uso via `init.sql`. As principais tabelas são:

- `invitees`: convidados e respostas
- `settings`: textos configuráveis do convite

---

## 📸 Exemplo de Tela

![Exemplo do painel admin](backend/static/antonio.jpg)

---

## 📄 Licença

Este projeto é open-source e pode ser utilizado livremente para fins pessoais ou educativos.