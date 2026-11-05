# Stage 1: Build the React application with Vite
FROM docker.io/library/node:20-alpine AS build

WORKDIR /app

# Copy dependency definitions
COPY package.json package-lock.json ./
RUN npm ci

# Copy client source code
COPY . .

# Accept build argument for Backend API URL (default to browser localhost:8000)
ARG VITE_API_URL=http://localhost:8000/api/v1
ENV VITE_API_URL=$VITE_API_URL

# Build the production bundle
RUN npm run build

# Stage 2: Serve static files using Nginx on port 3000
FROM docker.io/library/nginx:alpine

# Copy built static assets from Stage 1
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom nginx configuration listening on port 3000
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose frontend port 3000
EXPOSE 3000

# Start Nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
