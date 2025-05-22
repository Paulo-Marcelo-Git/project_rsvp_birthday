# backend/app.py

from flask import Flask, render_template, request, redirect, url_for, abort, Response, flash
import pymysql
import os
import uuid
from functools import wraps
from datetime import timedelta  # adicionada esta importação

app = Flask(__name__)
# Necessário para usar flash()
app.secret_key = os.getenv('SECRET_KEY', 'insira_uma_chave_secreta_aqui')

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/invite/<token>', methods=['GET', 'POST'])
def invite(token):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM invitees WHERE token = %s", (token,))
        invitee = cursor.fetchone()

    if not invitee:
        abort(404)

    if request.method == 'POST':
        response = request.form.get('response')
        if invitee['response'] is None and response in ['yes', 'no']:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE invitees SET response=%s, response_date=NOW() WHERE token=%s",
                    (response, token)
                )
                conn.commit()
        return redirect(url_for('invite', token=token))

    return render_template('invite.html', invitee=invitee)

# -----------------------------
# 🔐 Rotas protegidas de admin
# -----------------------------

def check_auth(username, password):
    return (
        username == os.getenv("ADMIN_USER") and
        password == os.getenv("ADMIN_PASS")
    )

def authenticate():
    return Response(
        "Acesso restrito.\n", 401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/respostas")
@requires_auth
def respostas():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, email, phone, response, response_date, token
            FROM invitees
            ORDER BY response_date IS NULL, response_date DESC
        """)
        convidados = cursor.fetchall()

    # Ajuste de fuso: subtrai 3 horas de cada response_date
    for row in convidados:
        if row['response_date']:
            row['response_date'] = row['response_date'] - timedelta(hours=3)

    return render_template('admin_responses.html', convidados=convidados)

@app.route("/admin/convidados/add", methods=['POST'])
@requires_auth
def add_convidado():
    name  = request.form.get('name')
    email = request.form.get('email') or None
    phone = request.form.get('phone')
    msg   = request.form.get('custom_message') or None

    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for('respostas'))

    token = uuid.uuid4().hex
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invitees (name, email, phone, token, custom_message) VALUES (%s, %s, %s, %s, %s)",
            (name, email, phone, token, msg)
        )
        conn.commit()

    flash(f"Convidado “{name}” adicionado com sucesso!", "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@requires_auth
def delete_convidado(id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM invitees WHERE id = %s", (id,))
        conn.commit()

    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for('respostas'))

if __name__ == "__main__":
    # Para rodar localmente: python app.py
    app.run(host="0.0.0.0", port=8000)
