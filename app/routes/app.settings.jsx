import { useState } from "react";
import prisma from "../db.server";
import { useEffect } from "react";
import { useFetcher } from "react-router";
import { authenticate } from "../shopify.server";
// import { Form, useActionData } from "react-router-dom";
import { useAppBridge } from "@shopify/app-bridge-react";
import { useLoaderData, useRouteError } from "react-router";
import { encrypt, decrypt } from "../functions/auth";

export const loader = async ({ request }) => {
  const { admin, session, redirect, cors, billing, scopes, sessionToken } =
    await authenticate.admin(request);

  // Default output
  let bingKey = "";
  let validGoogleConfig = false;

  // Fetch the record for the shop
  const auth = await prisma.auth.findUnique({
    where: { shop: session.shop },
  });

  if (auth?.bingApiKey) {
    const raw = auth.bingApiKey;

    // Basic sanity check: “3 dot segments”
    const isValidFormat = raw.split(".").length === 3;

    if (isValidFormat) {
      // decrypt your key (you already have your decrypt function)
      try {
        const originalKey = decrypt(raw);

        // mask helper: show first 4 + last 4 characters
        const maskKey = (k) => {
          if (k.length <= 8) return k; // extremely short edge case
          return `${k.slice(0, 4)}••••••••••••••••••••••••${k.slice(-4)}`;
        };

        bingKey = maskKey(originalKey);
      } catch (err) {
        console.error("Failed to decrypt bingIndexingUrl", err);
      }
    }
  }

  // console.log(auth);

  if (auth?.googleConfig) {
    const raw = auth.googleConfig;

    // Basic sanity check: “3 dot segments”
    const isValidFormat = raw.split(".").length === 3;

    if (isValidFormat) {
      validGoogleConfig = true;
    }
  }

  let currentSettings = {
    bingLimit: 10000,
    retryLimit: 3,
    googleLimit: 200,
    contentTypePreferences: [],
  };

  if (auth?.settings) {
    try {
      // If settings is a string, parse it
      currentSettings =
        typeof auth.settings === "string"
          ? JSON.parse(auth.settings)
          : auth.settings;
    } catch (err) {
      console.error("Failed to parse settings:", err);
    }
  }

  return {
    bing_key: bingKey,
    isGoogleConfig: validGoogleConfig,
    shopSettings: currentSettings,
  };
};

export async function action({ request }) {
  const { session } = await authenticate.admin(request);
  const formData = await request.formData();

  // Prepare update object for atomic operation
  const updateData = {};
  let hasChanges = false;

  // ==========================================
  // Handle Bing API Key
  // ==========================================
  const bingAction = formData.get("bingAction");
  const currentSettings = formData.get("shopSettings");

  console.log("Bing Action:", bingAction);

  if (bingAction === "update") {
    const key = formData.get("bing-secret");

    // Server-side validation
    if (!/^[a-zA-Z0-9]{32}$/.test(key)) {
      return { error: "Invalid Bing key format" };
    }

    const encryptedKey = encrypt(key);
    updateData.bingApiKey = encryptedKey;
    hasChanges = true;
    console.log("Bing API Key will be updated");
  } else if (bingAction === "delete") {
    updateData.bingApiKey = "";
    hasChanges = true;
    console.log("Bing API Key will be deleted");
  }

  // ==========================================
  // Handle Google Config
  // ==========================================
  const googleAction = formData.get("googleAction");
  console.log("Google Action:", googleAction);

  if (googleAction === "update") {
    try {
      const googleConfig = formData.get("data");

      if (!googleConfig) {
        return { error: "No Google configuration data provided" };
      }

      // Encrypt the JSON string
      const encryptedConfig = encrypt(googleConfig);
      updateData.googleConfig = encryptedConfig;
      hasChanges = true;
      console.log("Google Config will be updated for:", session.shop);
    } catch (err) {
      console.error("Error processing Google config:", err);
      return {
        error: "Invalid JSON format. Please paste the entire file content.",
      };
    }
  } else if (googleAction === "delete") {
    updateData.googleConfig = "";
    hasChanges = true;
    console.log("Google Config will be deleted");
  }

  // ==========================================
  // Handle Submission Settings (Content Types)
  // ==========================================
  const shopSettingsJSON = formData.get("shopSettingsJSON");
  console.log("Shop Settings JSON received:", shopSettingsJSON);

  if (shopSettingsJSON) {
    try {
      // **FIX: Parse the JSON string**
      const parsedSettings = JSON.parse(shopSettingsJSON);
      updateData.settings = parsedSettings;
      hasChanges = true;
      console.log("Settings will be updated:", parsedSettings);
    } catch (err) {
      console.error("Error parsing shop settings:", err);
      return { error: "Invalid settings format" };
    }
  }

  // ==========================================
  // Perform Single Atomic Update
  // ==========================================
  // Perform Single Atomic Update
  if (hasChanges) {
    console.log("Performing database update with:", updateData);

    await prisma.auth.upsert({
      where: { shop: session.shop },
      update: updateData,
      create: {
        shop: session.shop,
        ...updateData,
        settings: updateData.settings || {
          bingLimit: 10000,
          retryLimit: 3,
          googleLimit: 200,
          contentTypePreferences: [],
        },
      },
    });

    console.log("Successfully updated settings for shop:", session.shop);
    return { success: true };
  } else {
    console.log("No changes detected, skipping database update");
    return { success: true, message: "No changes to save" };
  }
}

/**
 * Validates if the JSON object is a valid Google Service Account Key.
 * @param {Object|string} jsonInput - The JSON object or string.
 * @returns {Object} { isValid: boolean, missingFields: string[] }
 */
function validateServiceAccountJson(jsonInput) {
  try {
    const data =
      typeof jsonInput === "string" ? JSON.parse(jsonInput) : jsonInput;

    // List of mandatory fields for a Google Service Account key
    const requiredFields = [
      "type",
      "project_id",
      "private_key_id",
      "private_key",
      "client_email",
      "client_id",
      "auth_uri",
      "token_uri",
    ];

    const missingFields = requiredFields.filter((field) => !data[field]);

    // Additional check: type must be 'service_account'
    const isServiceAccount = data.type === "service_account";

    // Additional check: private_key must contain the BEGIN PRIVATE KEY header
    const hasValidKeyFormat =
      data.private_key &&
      data.private_key.includes("-----BEGIN PRIVATE KEY-----");

    const isValid =
      missingFields.length === 0 && isServiceAccount && hasValidKeyFormat;

    return {
      isValid,
      missingFields,
      error: !isServiceAccount
        ? "Type is not 'service_account'"
        : !hasValidKeyFormat
          ? "Private key format is invalid"
          : "None",
    };
  } catch (e) {
    return { isValid: false, missingFields: [], error: "Invalid JSON format" };
  }
}

export default function SettingsPage() {
  const { bing_key, isGoogleConfig, shopSettings } = useLoaderData();

  // const result = useActionData();
  const fetcher = useFetcher();
  const shopify = useAppBridge();

  const [bingKeyError, setBingKeyError] = useState(null);
  const [bingStatus, setBingStatus] = useState("");
  const [bingKey, setBingKey] = useState(bing_key ?? "");

  const [dropZoneError, setdropZoneError] = useState(null);
  const [dropZoneDisabled, setdropZoneDisabled] = useState(isGoogleConfig);
  const [jsonData, setJsonData] = useState(null);

  const [settings, setSettings] = useState(shopSettings);

  const [dirtyForms, setDirtyForms] = useState({
    form1: false,
    form2: false,
    form3: false,
  });

  async function handleRetestServer() {
    try {
      setBingStatus("pending");

      const res = await fetch("/api/test-credentials", {
        method: "POST",
        body: JSON.stringify({ bing_key }),
      });

      if (!res.ok) throw new Error();

      const data = await res.json();

      if (data.valid) {
        setBingStatus("success");
      } else {
        setBingStatus("failed");
      }
    } catch (err) {
      setBingStatus("failed");
    }
  }

  // // optional toast when saved
  // if (result?.success) {
  //   shopify.toast.show("API key saved");
  // }

  // const isLoading =
  //   ["loading", "submitting"].includes(fetcher.state) &&
  //   fetcher.formMethod === "POST";

  // useEffect(() => {
  //   if (fetcher.data?.product?.id) {
  //     shopify.toast.show("Product created");
  //   }
  // }, [fetcher.data?.product?.id, shopify]);

  //////////////////////////////////////////////////////
  //////////// <----- FUNCTIONS AREA -----> ////////////
  //////////////////////////////////////////////////////

  function handleFormSubmit(event) {
    event.preventDefault();

    const formData = new FormData(event.target);
    const formEntries = Object.fromEntries(formData);

    console.log("Form-data-full", formEntries);

    const key = formData.get("bing-secret");
    console.log("bingApiKey");
    console.log(key);

    // Bing Changed
    if (dirtyForms.form1) {
      if (key == "") {
        // User wants to delete the api key
        formData.append("bingAction", "delete");

        console.log("bing request delete");
      } else {
        // Validate Key
        const isValid = /^[a-zA-Z0-9]{32}$/.test(key);
        if (!isValid) {
          setBingKeyError("Key must be 32 alphanumeric characters");
        } else {
          formData.append("bingAction", "update");
          console.log("bing request update");
        }
      }
      setDirtyForms((f) => ({ ...f, form1: false }));
    } else {
      console.log("BING NO CHANGES");
    }

    if (dirtyForms.form2) {
      if (jsonData == null) {
        // Change but not uploaded = Delete
        formData.append("googleAction", "delete");
        console.log("google request delete");
      } else {
        console.log("google request update");

        formData.append("googleAction", "update");
        formData.append("data", JSON.stringify(jsonData));
      }

      setDirtyForms((f) => ({ ...f, form2: false }));
    } else {
      console.log("GOOGLE NO DATA CHANGES");
    }

    const contentTypeRaw = formEntries["content-type"];

    if (dirtyForms.form3) {
      // turn into list array
      const indexableList = contentTypeRaw
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean); // removes empty entries

      console.log(shopSettings);
      formData.append(
        "shopSettingsJSON",
        JSON.stringify({
          ...shopSettings,
          contentTypePreferences: indexableList,
        }),
      );

      console.log("indexable list:", indexableList);
    } else {
      console.log("SETTINGS NO DATA CHANGES");
    }

    fetcher.submit(formData, { method: "POST" });
  }

  function handleRejected(event) {
    setdropZoneError(
      "This file type is not allowed. Please upload a JSON file.",
    );
  }

  function handleFileChange(event) {
    const files = event.currentTarget?.files;
    if (!files || files.length === 0) return;

    const file = files[0];

    // Optional: basic file validation
    if (file.type !== "application/json" && !file.name.endsWith(".json")) {
      setdropZoneError("Please upload a valid .json file.");
      return;
    }

    const reader = new FileReader();

    reader.onload = function (e) {
      const text = e.target.result;

      try {
        const _jsonData = JSON.parse(text);
        console.log(_jsonData);

        // Validate Structure
        const result = validateServiceAccountJson(_jsonData);

        if (!result.isValid) {
          setdropZoneError("Invalid Service Account Key");
          return;
        }

        setdropZoneError(null);
        setdropZoneDisabled(true);
        setJsonData(_jsonData);
        setDirtyForms((f) => ({ ...f, form2: true }));
      } catch (err) {
        console.log(err);
        setdropZoneError("The uploaded file is not valid JSON.");
      }
    };

    reader.onerror = function () {
      setdropZoneError("Unable to read the file. Please try again.");
    };

    reader.readAsText(file);
  }

  function handleFormReset(event) {
    event.preventDefault();

    // Bing Changed
    if (dirtyForms.form1) {
      setDirtyForms((f) => ({ ...f, form1: false }));
    } else {
      console.log("BING NO CHANGES REVERT");
    }

    if (dirtyForms.form2) {
      setdropZoneError(null);
      setdropZoneDisabled(isGoogleConfig); // revive Initial State UI
      setDirtyForms((f) => ({ ...f, form2: false }));
    } else {
      console.log("GOOGLE NO DATA CHANGES REVERT");
    }

    if (dirtyForms.form3) {
      setDirtyForms((f) => ({ ...f, form3: false }));
    } else {
      console.log("SETTINGS NO DATA CHANGES REVERT");
    }
  }

  function toggleContentType(value, isSelected) {
    setSettings((prev) => {
      let updated = [...prev.contentTypePreferences];

      if (isSelected) {
        // add if missing
        if (!updated.includes(value)) {
          updated.push(value);
        }
      } else {
        // remove if present
        updated = updated.filter((v) => v !== value);
      }

      return { ...prev, contentTypePreferences: updated };
    });
  }

  return (
    <s-page heading="Settings" inlineSize="small">
      <fetcher.Form
        method="post"
        onSubmit={handleFormSubmit}
        onReset={handleFormReset}
        data-save-bar
      >
        <s-stack gap="base">
          {/* Status card */}

          {bingStatus === "success" && (
            <s-banner
              heading="Connection successful"
              tone="success"
              dismissible
            >
              The server is online and Bing credentials are verified
              successfully.
            </s-banner>
          )}

          {bingStatus === "pending" && (
            <s-banner heading="Checking connection" tone="info" dismissible>
              We are testing your credentials and server connectivity. This may
              take a moment.
            </s-banner>
          )}

          {bingStatus === "failed" && (
            <s-banner heading="Connection failed" tone="critical" dismissible>
              We were unable to verify your Bing credentials. Please review your
              API key and try again.
              <s-button slot="secondary-actions" variant="secondary">
                Try again
              </s-button>
            </s-banner>
          )}

          {/* BING FORM */}
          <s-section heading="Credential Information">
            {/* <s-text tone="subdued">
                  Verifies whether the API credentials are valid and the server
                  can connect.
                </s-text>

                <s-button onClick={handleRetestServer}>
                  Test connection again
                </s-button> */}

            {/* API key input */}
            <s-password-field
              label="Bing WebMaster Api Key "
              name="bing-secret"
              error={bingKeyError}
              value={bingKey}
              onInput={(e) => setBingKey(e.target.value)}
              onChange={() => setDirtyForms((f) => ({ ...f, form1: true }))}
              maxLength={32}
              minLength={32}
              details="Must be at least 32 alphanumeric characters long"
              placeholder="Enter API Key"
            />
          </s-section>
          {/* </form> */}

          {/* <fetcher.Form
            method="post"
            onSubmit={handleGoogleSubmit}
            onReset={(event) => {
              event.preventDefault();
              setdropZoneError(null);
              setdropZoneDisabled(isGoogleConfig); // revive Initial State UI
              setDirtyForms((f) => ({ ...f, form2: false }));
            }}
            onChange={() => setDirtyForms((f) => ({ ...f, form2: true }))}
            data-save-bar
          > */}
          <input
            type="hidden"
            id="google-removed-flag"
            name="googleRemovedFlag"
            value="0"
          />

          <s-section heading="Google Configuration File">
            {/* Show File */}
            {dropZoneDisabled == true && (
              <s-grid gridTemplateColumns="1fr auto" alignItems="center">
                <s-box
                  padding="small-100"
                  background="subdued"
                  borderRadius="small"
                >
                  <s-stack direction="inline" gap="small-300">
                    <s-icon type="file" />
                    <s-paragraph>Config.json</s-paragraph>
                  </s-stack>
                </s-box>

                {/* Remove / reset button */}
                <s-button
                  variant="tertiary"
                  tone="critical"
                  onClick={() => {
                    // delete your uploaded File state
                    setdropZoneDisabled(false); // Show DropZone
                    setdropZoneError(null);

                    // UI change replication
                    const hidden = document.getElementById(
                      "google-removed-flag",
                    );
                    hidden.value = hidden.value === "1" ? "0" : "1";

                    // dispatch a real change **on the input**
                    hidden.dispatchEvent(new Event("input", { bubbles: true }));
                    hidden.dispatchEvent(
                      new Event("change", { bubbles: true }),
                    );

                    setJsonData(null);
                    setDirtyForms((f) => ({ ...f, form2: true }));
                  }}
                >
                  <s-icon type="delete" />
                </s-button>
              </s-grid>
            )}
            {dropZoneDisabled == false && (
              <s-drop-zone
                accept=".json"
                label="Upload Google Console API Key"
                error={dropZoneError}
                disabled={dropZoneDisabled}
                onChange={handleFileChange}
                onDropRejected={handleRejected}
              />
            )}
          </s-section>

          {/* <fetcher.Form
            method="post"
            onSubmit={baseSubmit}
            onReset={(event) => {
              event.preventDefault();
            }}
            onChange={() => setDirtyForms((f) => ({ ...f, form3: true }))}
            data-save-bar
          > */}
          <s-stack gap="base">
            {/* === */}
            {/* Notifications */}
            {/* === */}
            <s-section heading="Submission settings">
              <s-choice-list
                label="Prefered Content Type"
                name="content-type"
                multiple
                onChange={() => setDirtyForms((f) => ({ ...f, form3: true }))}
              >
                <s-choice
                  value="products"
                  selected={settings.contentTypePreferences.includes(
                    "products",
                  )}
                  onChange={(selected) =>
                    toggleContentType("products", selected)
                  }
                >
                  Products
                </s-choice>

                <s-choice
                  value="collections"
                  selected={settings.contentTypePreferences.includes(
                    "collections",
                  )}
                  onChange={(selected) =>
                    toggleContentType("collections", selected)
                  }
                >
                  Collections
                </s-choice>

                <s-choice
                  value="pages"
                  selected={settings.contentTypePreferences.includes("pages")}
                  onChange={(selected) => toggleContentType("pages", selected)}
                >
                  Online store pages
                </s-choice>

                <s-choice
                  value="blog_posts"
                  selected={settings.contentTypePreferences.includes(
                    "blog_posts",
                  )}
                  onChange={(selected) =>
                    toggleContentType("blog_posts", selected)
                  }
                >
                  Blog posts
                </s-choice>
              </s-choice-list>
            </s-section>

            {/* === */}
            {/* Tools */}
            {/* === */}
            <s-section heading="Tools">
              <s-stack
                gap="none"
                border="base"
                borderRadius="base"
                overflow="hidden"
              >
                <s-box padding="small-100">
                  <s-grid
                    gridTemplateColumns="1fr auto"
                    alignItems="center"
                    gap="base"
                  >
                    <s-box>
                      <s-heading>Reset app settings</s-heading>
                      <s-paragraph color="subdued">
                        Reset all settings to their default values. This action
                        cannot be undone.
                      </s-paragraph>
                    </s-box>
                    <s-button tone="critical">Reset</s-button>
                  </s-grid>
                </s-box>
                <s-box paddingInline="small-100">
                  <s-divider />
                </s-box>

                <s-box padding="small-100">
                  <s-grid
                    gridTemplateColumns="1fr auto"
                    alignItems="center"
                    gap="base"
                  >
                    <s-box>
                      <s-heading>Export settings</s-heading>
                      <s-paragraph color="subdued">
                        Download a backup of all your current settings.
                      </s-paragraph>
                    </s-box>
                    <s-button>Export</s-button>
                  </s-grid>
                </s-box>
              </s-stack>
            </s-section>
          </s-stack>
        </s-stack>
      </fetcher.Form>
    </s-page>
  );
}
