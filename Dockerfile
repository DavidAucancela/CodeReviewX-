FROM python:3.12-slim

# eslint para análisis JS — fijado a v8: la v9 eliminó --no-eslintrc y --env,
# que static_analyzer.py usa para analizar archivos sueltos sin config de proyecto.
RUN apt-get update && apt-get install -y git nodejs npm && \
    npm install -g eslint@8 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
