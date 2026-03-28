FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install

# Copy source
COPY apps/web/ .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
