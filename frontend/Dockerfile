FROM node:20-alpine AS build

WORKDIR /app
ARG VITE_API_BASE=/api
ARG VITE_IDENTITY_PLATFORM_API_KEY=
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_IDENTITY_PLATFORM_API_KEY=${VITE_IDENTITY_PLATFORM_API_KEY}

COPY package.json package-lock.json* /app/
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . /app
RUN npm run build

FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
