import { authenticate } from "../shopify.server";
import db from "../db.server";

export const action = async ({ request }) => {
  console.log(`Received webhook on BACKEND`);
  const { topic, shop, session, payload } = await authenticate.webhook(request);

  console.log(`Received ${topic} webhook for ${shop}`);

  console.log("Webhook details:", {
    topic,
    shop,
    session,
    payload,
  });

  const productId = BigInt(payload.id);

  switch (topic) {
    case "PRODUCTS_CREATE":
    case "PRODUCTS_UPDATE": {
      const productUrl = `https://${shop}/products/${payload.handle}`;
      const isActive = payload.status != "draft";

      await db.urlEntry.upsert({
        where: {
          shop_webUrl: {
            shop,
            webUrl: productUrl,
          },
        },
        update: {
          indexAction: isActive ? "INDEX" : "DELETE",
          status: "PENDING",
          // metadata: buildProductMetadata(payload),   // Need to think more about this
          lastEventAt: new Date(),
        },
        create: {
          shop,
          baseId: productId,
          webUrl: productUrl,
          indexAction: isActive ? "INDEX" : "DELETE",
          status: "PENDING",
          attempts: 1,
          lastIndexedAt: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
          // metadata: buildProductMetadata(payload),
        },
      });
      break;
    }
    case "PRODUCTS_DELETE": {
      await db.urlEntry.update({
        where: {
          shop_baseId: {
            shop,
            baseId: productId,
          },
        },
        data: {
          indexAction: "DELETE",
          status: "PENDING",
          lastEventAt: new Date(),
        },
      });
      break;
    }

    default:
      console.log("Unhandled topic:", topic);
  }

  return new Response();
};
