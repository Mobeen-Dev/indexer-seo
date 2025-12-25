/*
  Warnings:

  - You are about to drop the column `needsIndexing` on the `UrlEntry` table. All the data in the column will be lost.

*/
-- CreateEnum
CREATE TYPE "IndexAction" AS ENUM ('INDEX', 'DELETE', 'IGNORE');

-- DropIndex
DROP INDEX "UrlEntry_needsIndexing_idx";

-- AlterTable
ALTER TABLE "UrlEntry" DROP COLUMN "needsIndexing",
ADD COLUMN     "indexAction" "IndexAction" NOT NULL DEFAULT 'INDEX';

-- CreateIndex
CREATE INDEX "UrlEntry_indexAction_idx" ON "UrlEntry"("indexAction");
