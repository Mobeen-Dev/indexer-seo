-- CreateTable
CREATE TABLE "IndexTask" (
    "id" BIGSERIAL NOT NULL,
    "shop" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "isCompleted" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMPTZ,

    CONSTRAINT "IndexTask_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "IndexTask_shop_isCompleted_idx" ON "IndexTask"("shop", "isCompleted");
