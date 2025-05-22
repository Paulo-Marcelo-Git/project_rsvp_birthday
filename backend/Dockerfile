#backend\Dockerfile

FROM python:3.12-slim

# Diretório de trabalho
WORKDIR /app

# Copia tudo
COPY . .

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta usada pelo Flask
EXPOSE 8000

# Comando default (pode ser sobrescrito pelo compose)
CMD ["flask", "run", "--host=0.0.0.0", "--port=8000"]
