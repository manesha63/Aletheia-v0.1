import { PrismaClient } from "@prisma/client";
// Encryption middleware temporarily disabled - needs update for Prisma 6+
// import { createEncryptionMiddleware } from './prisma-encryption';

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  });

// TODO: Update encryption middleware for Prisma 6+ extensions API
// The $use method was deprecated in Prisma 5 and removed in Prisma 6
// See: https://www.prisma.io/docs/orm/prisma-client/client-extensions
// prisma.$use(createEncryptionMiddleware());

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;

export default prisma;