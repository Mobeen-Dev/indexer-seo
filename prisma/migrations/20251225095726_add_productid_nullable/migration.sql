/*
  Warnings:

  - A unique constraint covering the columns `[shop,productId]` on the table `UrlEntry` will be added. If there are existing duplicate values, this will fail.
  - Added the required column `productId` to the `UrlEntry` table without a default value. This is not possible if the table is not empty.

*/
-- AlterTable
ALTER TABLE "UrlEntry" ADD COLUMN     "productId" BIGINT NOT NULL;

-- CreateIndex
CREATE UNIQUE INDEX "UrlEntry_shop_productId_key" ON "UrlEntry"("shop", "productId");
