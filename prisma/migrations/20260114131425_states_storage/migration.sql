-- CreateTable
CREATE TABLE "ShopFeatureStates" (
    "id" BIGSERIAL NOT NULL,
    "shop" TEXT NOT NULL,
    "home" JSONB NOT NULL,
    "urlSubmission" JSONB NOT NULL,
    "pricing" JSONB NOT NULL,
    "settings" JSONB NOT NULL,
    "submissionsHistory" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ShopFeatureStates_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "ShopFeatureStates_shop_key" ON "ShopFeatureStates"("shop");

-- CreateIndex
CREATE INDEX "ShopFeatureStates_shop_idx" ON "ShopFeatureStates"("shop");
