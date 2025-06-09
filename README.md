
# Comemore+

**Comemore+** é uma aplicação web para gerenciamento de convites de aniversário com sistema de RSVP online. A plataforma permite que o anfitrião envie convites personalizados e acompanhe as respostas em tempo real via uma interface administrativa segura.

---

## ✨ Funcionalidades

- 📬 Geração de links únicos de convite por convidado
- ✅ Registro de confirmação de presença (Sim ou Não)
- 📝 Edição personalizada dos textos do convite
- 👤 Área administrativa com login
- 🗑️ Remoção de convidados
- ➕ Cadastro manual de convidados
- 🌈 Layout agradável com cores suaves (rosa e azul claro)
- 🔒 Autenticação com Flask-Login
- 🐳 Containerização com Docker e Docker Compose

---

## 🖼️ Captura de tela

Página do convite:

![Convite](backend/static/antonio.jpg)

---

## 🚀 Tecnologias Utilizadas

- Python 3.12
- Flask 3.x
- MySQL 8.x
- Flask-Login
- Bootstrap 5
- Docker + Docker Compose
- dotenv

---

## 📦 Estrutura do Projeto

```
project_rsvp_birthday/
│
├── backend/
│   ├── app.py                # Código principal do Flask
│   ├── init.sql              # Script de criação e população do banco
│   ├── requirements.txt      # Dependências do backend
│   ├── Dockerfile            # Dockerfile para o backend
│   ├── static/
│   │   ├── antonio.jpg       # Foto usada no convite
│   │   └── admin.css         # Estilo da área administrativa
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── invite.html
│       └── admin_responses.html
│
├── .env                      # Variáveis de ambiente
├── .gitignore
└── docker-compose.yml        # Orquestração dos containers
```

---

## ⚙️ Como executar

### Pré-requisitos

- Docker
- Docker Compose

### Passos

```bash
# Clone o repositório
git clone https://github.com/seuusuario/project_rsvp_birthday.git
cd project_rsvp_birthday

# Inicie os containers
docker-compose up --build
```

Acesse:
- **Frontend (Convite):** `http://localhost:3000/invite/<token>`
- **Admin:** `http://localhost:3000/login`

---

## 🔑 Acesso à Área Administrativa

As credenciais estão definidas no arquivo `.env`:

```
ADMIN_USER= User
ADMIN_PASS= Senha
```

---

## 🛠️ Variáveis de Ambiente (.env)

```env
# MySQL
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD="sua_senha"
DB_HOST=db

# Admin credentials
ADMIN_USER=admin
ADMIN_PASS=sua_senha
SECRET_KEY=sua_chave_secreta
```

---

## 📌 Observações

- O banco de dados é iniciado com textos padrão para o convite.
- Os dados dos convidados são armazenados na tabela `invitees`.
- As respostas (RSVP) são registradas com data/hora.
- O projeto é voltado inicialmente para o aniversário do Antony, mas facilmente adaptável para qualquer pessoa.

---

## 📄 Licença

Projeto desenvolvido para fins educacionais. Sinta-se livre para adaptar.

---

## 💡 Autor

Desenvolvido por Paulo Marcelo Cardoso Da Silva. Em caso de dúvidas ou sugestões, entre em contato!
