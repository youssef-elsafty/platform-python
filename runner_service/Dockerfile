FROM python:3.12-alpine
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY server.py /app/
EXPOSE 8081
CMD ["python", "server.py"]
