FROM python:3.12-alpine
WORKDIR /app
COPY . /app/
EXPOSE 8080
CMD ["python", "app.py"]
