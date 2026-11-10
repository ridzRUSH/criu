FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir flask redis
COPY app.py .
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-u", "app.py"]
