FROM python:3.12-alpine

# Security: Create unprivileged non-root user
RUN addgroup -S sandboxgroup && adduser -S sandboxuser -G sandboxgroup

# Working directory inside sandbox
WORKDIR /home/sandboxuser/app

# Drop root privileges permanently
USER sandboxuser

# Default command: runs python in isolated, unbuffered mode
CMD ["python", "-I", "-B", "/home/sandboxuser/app/solution.py"]
