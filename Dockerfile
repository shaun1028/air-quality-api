FROM php:8.2-cli

WORKDIR /app

COPY . .

RUN docker-php-ext-install mysqli pdo pdo_mysql

EXPOSE 8080

CMD php -S 0.0.0.0:$PORT -t /app
