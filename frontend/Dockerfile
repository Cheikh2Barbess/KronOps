# Deux facons de lancer l'ecran :
# - "dev" (par defaut avec docker-compose.yml) : recharge le code a chaud, mais compile
#   chaque page a sa premiere visite, donc lent, surtout sous Docker Desktop Windows.
# - "prod" (avec docker-compose.front-prod.yml) : pages compilees une fois au build, rapide.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS prod
# Les redirections /api/* vers Django sont figees au build : l'adresse doit etre connue ici.
ENV API_INTERNAL_URL=http://backend:8000
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build && rm -f AGENTS.md
EXPOSE 3000
CMD ["npm", "run", "start"]

FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
