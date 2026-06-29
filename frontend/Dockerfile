# WorldBase frontend — build the Vite/React SPA, serve via Caddy (TLS + /api proxy)
FROM node:20-alpine AS build

WORKDIR /app

# Cesium Ion token + Flowsint URL are baked at build time (Vite env)
ARG VITE_CESIUM_ION_TOKEN=""
ARG VITE_FLOWSINT_URL="http://localhost:5173"
ARG VITE_WORLDBASE_API_KEY=""
ARG VITE_WORLDBASE_AGENT_BUS=""
ENV VITE_CESIUM_ION_TOKEN=$VITE_CESIUM_ION_TOKEN \
    VITE_FLOWSINT_URL=$VITE_FLOWSINT_URL \
    VITE_WORLDBASE_API_KEY=$VITE_WORLDBASE_API_KEY \
    VITE_WORLDBASE_AGENT_BUS=$VITE_WORLDBASE_AGENT_BUS

COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts

COPY . .
RUN npm run build

# --- Serve stage: Caddy serves the SPA and reverse-proxies /api to the backend
FROM caddy:2-alpine
COPY --from=build /app/dist /srv
# Caddyfile is mounted at runtime via docker-compose (./Caddyfile)
