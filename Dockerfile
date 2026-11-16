FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CAMPUS_HOST=0.0.0.0
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home mailtool \
    && mkdir /app/data && chown mailtool:mailtool /app/data
USER mailtool
EXPOSE 8765
CMD ["campus-mail", "serve"]
