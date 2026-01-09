import os
import base64
from config import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_HEX = settings.JOINT_KEY

# Validate key
if not MASTER_KEY_HEX:
    raise ValueError("MASTER_KEY environment variable must be set")

if len(MASTER_KEY_HEX) != 64:
    raise ValueError("MASTER_KEY must be 32 bytes (64 hex chars) for AES-256-GCM")

MASTER_KEY = bytes.fromhex(MASTER_KEY_HEX)


def encrypt(plaintext: str) -> str:
    """
    Encrypts plaintext using AES-256-GCM

    Args:
        plaintext: The text to encrypt

    Returns:
        Encrypted payload in format: iv.tag.ciphertext (all base64)
    """
    # Generate random 12-byte IV
    iv = os.urandom(12)

    # Create AESGCM instance
    aesgcm = AESGCM(MASTER_KEY)

    # Encrypt (returns ciphertext + tag combined)
    ciphertext_and_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)

    # GCM returns: ciphertext || tag (last 16 bytes are the tag)
    ciphertext = ciphertext_and_tag[:-16]
    tag = ciphertext_and_tag[-16:]

    # Format: iv.tag.ciphertext (all base64)
    return ".".join(
        [
            base64.b64encode(iv).decode("utf-8"),
            base64.b64encode(tag).decode("utf-8"),
            base64.b64encode(ciphertext).decode("utf-8"),
        ]
    )


def decrypt(payload: str) -> str:
    """
    Decrypts an encrypted payload

    Args:
        payload: Encrypted string in format: iv.tag.ciphertext

    Returns:
        Decrypted plaintext string
    """
    parts = payload.split(".")

    if len(parts) != 3:
        raise ValueError(
            "Invalid encrypted payload format (expected: iv.tag.ciphertext)"
        )

    iv_b64, tag_b64, ct_b64 = parts

    if not iv_b64 or not tag_b64 or not ct_b64:
        raise ValueError("Invalid encrypted payload format")

    # Decode base64 components
    iv = base64.b64decode(iv_b64)
    tag = base64.b64decode(tag_b64)
    ciphertext = base64.b64decode(ct_b64)

    # Create AESGCM instance
    aesgcm = AESGCM(MASTER_KEY)

    # GCM expects: ciphertext || tag
    ciphertext_and_tag = ciphertext + tag

    # Decrypt
    try:
        plaintext = aesgcm.decrypt(iv, ciphertext_and_tag, None)
        return plaintext.decode("utf-8")
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")


# Example usage
if __name__ == "__main__":
    # Test encryption/decryption
    test_data = "Hello, secure world! 🔐"
    print(f"Original: {test_data}")

    encrypted = encrypt(test_data)
    print(f"Encrypted: {encrypted}")

    decrypted = decrypt(encrypted)
    print(f"Decrypted: {decrypted}")

    print(f"Match: {'✅' if test_data == decrypted else '❌'}")

    # Test with a Node.js encrypted message (example)
    print("\n--- Testing Node.js interoperability ---")
    print("Encrypt a message in Node.js and paste it here to test decryption:")

    # Example: decrypt a message encrypted by Node.js
    # nodejs_encrypted = "your.encrypted.message"
    # print(f'Decrypted from Node.js: {decrypt(nodejs_encrypted)}')
