/*
  Warnings:

  - A unique constraint covering the columns `[shop,url]` on the table `IndexTask` will be added. If there are existing duplicate values, this will fail.

*/
-- CreateIndex
CREATE UNIQUE INDEX "IndexTask_shop_url_key" ON "IndexTask"("shop", "url");
