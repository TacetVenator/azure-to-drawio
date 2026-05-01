FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --upgrade pip && \
    pip install pytest pytest-html && \
    pip install -r tools/azdisc_ui/requirements.txt

EXPOSE 18427

CMD ["python", "-m", "uvicorn", "tools.azdisc_ui.__main__:create_app", "--factory", "--host", "0.0.0.0", "--port", "18427"]
