FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY minerador/ minerador/
COPY web/ web/
COPY run.py .

ENV PYTHONUNBUFFERED=1
ENV MINERADOR_HOST=0.0.0.0
ENV MINERADOR_PORTA=8765
ENV MINERADOR_SEM_NAVEGADOR=1

EXPOSE 8765

CMD ["python", "run.py", "--host", "0.0.0.0", "--porta", "8765", "--sem-navegador"]
