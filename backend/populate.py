#backend\populate.py

import os
import pymysql
import uuid

conn = pymysql.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "rsvp_secret"),
    database=os.getenv("DB_NAME", "rsvp_db"),
    cursorclass=pymysql.cursors.DictCursor
)

cursor = conn.cursor()

guests = [
    ("Paulo Marcelo", "11999990001", "pmc.silva20@gmail.com"),
    #("Maria Oliveira", "11999990002", "maria@gmail.com"),
    #("Carlos Souza", "11999990003", "carlos@gmail.com"),
    #("Fernanda Lima", "11999990004", "fernanda@gmail.com"),
]

for name, phone, email in guests:
    token = uuid.uuid4().hex
    cursor.execute("INSERT INTO invitees (name, phone, email, token) VALUES (%s, %s, %s, %s)",
                   (name, phone, email, token))

conn.commit()
cursor.close()
conn.close()

print("Convidados inseridos com sucesso!")