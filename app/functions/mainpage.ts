// Get `/products/abc` from full URL
export function extractPath(originalUrl: string, shop: string) {
  try {
    const url = new URL(originalUrl);
    return url.pathname; // already starts with `/`
  } catch {
    return originalUrl;
  }
}

// Friendly label from path
export function getTypeFromPath(path: string) {
  path = path.substring(0, path.indexOf("/", 1));
  if (path.includes("/products")) return "Product";
  if (path.includes("/collections")) return "Collection";
  if (path.includes("/blogs")) return "Blog";
  return "Page";
}

// Action display from indexAction
export function getActionLabel(path: string, indexAction: string) {
  const type = getTypeFromPath(path);

  switch (indexAction) {
    case "INDEX":
      return `${type} Updated`;

    case "DELETE":
      return `${type} Deleted`;

    case "IGNORE":
      return `${type} Changes`;

    default:
      return `${type} ${indexAction}`;
  }
}

// Prisma enum → badge tone
export function getToneFromStatus(status: string) {
  switch (status) {
    case "COMPLETED":
      return { tone: "success", label: "Success" };
    case "PROCESSING":
      return { tone: "info", label: "Processing" };
    case "PENDING":
      return { tone: "warning", label: "Pending" };
    case "FAILED":
      return { tone: "critical", label: "Failed" };
    default:
      return { tone: "base", label: status };
  }
}

// "2 hours ago" from Date
export function timeAgo(date: Date) {
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);

  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return `${days} days ago`;
}
