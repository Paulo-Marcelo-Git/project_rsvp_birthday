# Project RSVP Birthday

Um sistema simples de RSVP online para aniversário infantil, construído com Flask, MySQL e Docker Compose.

---

## 🚀 Funcionalidades

* **Convite online**: cada convidado recebe um token único e vê a foto do aniversariante.
* **Registro de presença**: convidados respondem “Sim” ou “Não” e a resposta é registrada com data/hora.
* **Dashboard de administração**: lista única com status das respostas e link direto para visualizar convite.
* **Containerização completa**: banco MySQL e backend Flask orquestrados via Docker Compose.

## 🎯 Pré-requisitos

* Docker (versão ≥ 20.10)
* Docker Compose (plugin `docker compose` integrado ao Docker Desktop)
* Git (para clonar ou gerenciar o repositório)

> Opcional (para rodar local fora de containers):
>
> * Python 3.12
> * Pipenv ou virtualenv

## 🛠️ Instalação e execução

1. **Clone o repositório**

   ```bash
   git clone https://github.com/SeuUser/project_rsvp_birthday.git
   cd project_rsvp_birthday
   ```

2. **Copie e configure o arquivo de ambiente**

   ```bash
   cp .env.example .env
   # Edite .env com suas credenciais e parâmetros de conexão
   ```

3. **Suba os containers**

   ```bash
   docker compose up --build -d
   ```

4. **(Opcional) Popule dados de exemplo**

   ```bash
   docker compose exec backend python populate.py
   ```

5. **Acesse as páginas**

   * Convite de um convidado: `http://localhost:5000/invite/<token>`
   * Dashboard admin: `http://localhost:5000/admin/respostas`

6. **Parar e limpar** (sem perder dados)

   ```bash
   docker compose stop
   docker compose start
   # ou
   docker compose down    # sem -v
   docker compose up -d
   ```

---

## 📂 Estrutura do repositório

```
project_rsvp_birthday/
├── backend/
│   ├── Dockerfile
│   ├── app.py
│   ├── init.sql
│   ├── populate.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── static/
│   │   ├── admin.css
│   │   └── antonio.jpg
│   └── templates/
│       ├── base.html
│       ├── invite.html
│       ├── admin_responses.html
│       └── admin_list.html  <!-- opcional, pode remover se não usar -->
├── docker-compose.yml
└── README.md
```

---

## 🎓 Como contribuir

1. Fork este repositório.
2. Crie uma branch: `git checkout -b feature/minha-melhora`.
3. Faça suas alterações e commite: `git commit -am 'Adiciona nova feature X'`.
4. Envie para o seu fork: `git push origin feature/minha-melhora`.
5. Abra um Pull Request e aguarde revisão.

---

## 📜 Licença

Este projeto está sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.
