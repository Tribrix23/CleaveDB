use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Key, Nonce,
};
use std::sync::OnceLock;
use rand::{RngCore, rngs::OsRng};

static CIPHER: OnceLock<Aes256Gcm> = OnceLock::new();

pub fn init_crypto(key_bytes: &[u8]) {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(key_bytes);
    let hash = hasher.finalize();
    
    // We use from_slice (which is deprecated but works for now)
    let key = Key::<Aes256Gcm>::from_slice(&hash);
    CIPHER.set(Aes256Gcm::new(key)).ok();
}

pub fn encrypt_data(data: &[u8]) -> Vec<u8> {
    if let Some(cipher) = CIPHER.get() {
        let mut nonce_bytes = [0u8; 12];
        OsRng.fill_bytes(&mut nonce_bytes);
        
        let nonce = Nonce::from_slice(&nonce_bytes);
        let mut encrypted = cipher.encrypt(nonce, data).expect("Encryption failed");
        
        let mut out = nonce_bytes.to_vec();
        out.append(&mut encrypted);
        out
    } else {
        data.to_vec()
    }
}

pub fn decrypt_data(data: &[u8]) -> Vec<u8> {
    if let Some(cipher) = CIPHER.get() {
        if data.len() < 12 {
            return data.to_vec();
        }
        let nonce = Nonce::from_slice(&data[0..12]);
        cipher.decrypt(nonce, &data[12..]).expect("Decryption failed! Invalid key or corrupted data.")
    } else {
        data.to_vec()
    }
}

pub const OVERHEAD: usize = 28; // 12 bytes nonce + 16 bytes MAC
