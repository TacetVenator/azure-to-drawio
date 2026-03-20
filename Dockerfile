FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --upgrade pip && \
    pip install pytest pytest-html

# Optional: install any other dependencies
# RUN pip install -r requirements.txt

CMD ["/bin/bash"]
