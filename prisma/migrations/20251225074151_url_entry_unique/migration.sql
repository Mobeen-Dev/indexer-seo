/*
  Warnings:

  - A unique constraint covering the columns `[shop,originalUrl]` on the table `UrlEntry` will be added. If there are existing duplicate values, this will fail.
  - Added the required column `lastEventAt` to the `UrlEntry` table without a default value. This is not possible if the table is not empty.

*/
-- AlterTable
ALTER TABLE "UrlEntry" ADD COLUMN     "lastEventAt" TIMESTAMP(3) NOT NULL,
ADD COLUMN     "lastIndexedAt" TIMESTAMP(3),
ADD COLUMN     "needsIndexing" BOOLEAN NOT NULL DEFAULT true;

-- CreateIndex
CREATE INDEX "UrlEntry_needsIndexing_idx" ON "UrlEntry"("needsIndexing");

-- CreateIndex
CREATE UNIQUE INDEX "UrlEntry_shop_originalUrl_key" ON "UrlEntry"("shop", "originalUrl");
