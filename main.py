import numpy as np
import cv2
import os
import hashlib
import pickle
import time
import zstandard as zstd
from numba import njit
import matplotlib.pyplot as plt

# --- PHASE 2: JIT-ACCELERATED HYPERCHAOTIC ENGINE ---
@njit(fastmath=True)
def fast_chaos_engine(steps, state, params):
    x, y, z, w, v = state
    a, b, c, d, e = params
    
    sequences = np.zeros((steps, 5), dtype=np.float64) 
    
    # 2000-step warm-up to eliminate initial transients
    for _ in range(2000):
        x, y, z, w, v = np.sin(a*y)-z*np.cos(b*x), np.sin(c*z)-w*np.cos(d*y), \
                       np.sin(e*w)-v*np.cos(a*z), np.sin(b*v)-x*np.cos(c*w), \
                       np.sin(d*x)-y*np.cos(e*v)
                       
    for i in range(steps):
        x_n = np.sin(a*y) - z*np.cos(b*x)
        y_n = np.sin(c*z) - w*np.cos(d*y)
        z_n = np.sin(e*w) - v*np.cos(a*z)
        w_n = np.sin(b*v) - x*np.cos(c*w)
        v_n = np.sin(d*x) - y*np.cos(e*v)
        
        x, y, z, w, v = x_n, y_n, z_n, w_n, v_n
        
        # NO MODULO SCALING. Store the raw floats for full precision.
        sequences[i, 0], sequences[i, 1], sequences[i, 2], sequences[i, 3], sequences[i, 4] = x, y, z, w, v
        
    return sequences

class Research5DEncryptor:
    def __init__(self, secret_key="hehe234"):
        self.salt_hash = hashlib.sha256(secret_key.encode()).digest()
        self.vault_id = self.salt_hash.hex()[:8]
        self.params = np.array([3.5, 3.5, 3.5, 3.5, 3.5], dtype=np.float64)

    def _derive_keys(self, img_hash):
        final_key = bytearray([b1 ^ b2 for b1, b2 in zip(img_hash, self.salt_hash)])
        seeds = [int.from_bytes(final_key[i*6:(i+1)*6], 'big') for i in range(5)]
        return np.array([(s / (2**48)) + 1e-5 for s in seeds], dtype=np.float64)

    # --- PHASE 3: CIPHER CORE (COMPRESSION + BI-DIRECTIONAL DIFFUSION) ---
    def encrypt_block(self, block_3d):
        H, W, D = block_3d.shape
        img_hash = hashlib.sha256(block_3d.tobytes()).digest()
        initial_state = self._derive_keys(img_hash)
        
        cctx = zstd.ZstdCompressor(level=9) 
        compressed_data = cctx.compress(block_3d.tobytes())
        data_to_encrypt = np.frombuffer(compressed_data, dtype=np.uint8)
        total = len(data_to_encrypt)
        
        chaos_seq = fast_chaos_engine(max(total, 20000), initial_state, self.params)
        
        # 1. Confusion (Permutation)
        seed = int((np.abs(chaos_seq[0,0]) * 10**14) % (2**32))
        rng = np.random.default_rng(seed)
        perm = rng.permutation(total)
        scrambled = data_to_encrypt[perm].astype(np.uint16)

        # 2. Multi-Dimensional XOR Keys for Bi-directional Diffusion
        kf_raw = (np.abs(chaos_seq[:, 0])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 1])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64)
        kf = np.resize((kf_raw % 256).astype(np.uint16), total)
        cipher_f = np.bitwise_xor.accumulate(np.bitwise_xor(scrambled, kf))
        
        kb_raw = (np.abs(chaos_seq[:, 2])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 4])*10**14).astype(np.uint64)
        kb = np.resize((kb_raw % 256).astype(np.uint16), total)
        cipher_b = np.bitwise_xor.accumulate(np.bitwise_xor(cipher_f[::-1], kb[::-1]))[::-1]
        
        return cipher_b.astype(np.uint8), img_hash, seed

    def decrypt_block(self, cipher, img_hash, shuffle_seed, dims):
        total = len(cipher)
        initial_state = self._derive_keys(img_hash)
        chaos_seq = fast_chaos_engine(max(total, 20000), initial_state, self.params)
        flat_c = cipher.astype(np.uint16)

        # Inverse Backward Diffusion
        kb_raw = (np.abs(chaos_seq[:, 2])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 4])*10**14).astype(np.uint64)
        kb = np.resize((kb_raw % 256).astype(np.uint16), total)
        shifted_b = np.roll(flat_c, -1); shifted_b[-1] = 0
        dec_b = np.bitwise_xor(np.bitwise_xor(flat_c, shifted_b), kb)
        
        # Inverse Forward Diffusion
        kf_raw = (np.abs(chaos_seq[:, 0])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 1])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64)
        kf = np.resize((kf_raw % 256).astype(np.uint16), total)
        shifted_f = np.roll(dec_b, 1); shifted_f[0] = 0
        dec_f = np.bitwise_xor(np.bitwise_xor(dec_b, shifted_f), kf).astype(np.uint8)

        # Inverse Permutation
        rng = np.random.default_rng(shuffle_seed); perm = rng.permutation(total)
        inv_perm = np.empty_like(perm); inv_perm[perm] = np.arange(total)
        
        dctx = zstd.ZstdDecompressor()
        return np.frombuffer(dctx.decompress(dec_f[inv_perm].tobytes()), dtype=np.uint8).reshape(dims)

    # --- PIXEL HOOKS FOR SECURITY VALIDATION SCRIPTS ---
    def encrypt_block_pixels_only(self, block_3d):
        """Bypasses Zstd to test raw Chaos Entropy (Required by Reviewers)"""
        H, W, D = block_3d.shape
        total = H * W * D
        img_hash = hashlib.sha256(block_3d.tobytes()).digest()
        initial_state = self._derive_keys(img_hash)
        
        # H*W*D ensures we have enough unique keys for every pixel (Fixes FFT failure)
        chaos_seq = fast_chaos_engine(max(total, 20000), initial_state, self.params)
        
        flat = block_3d.flatten().astype(np.uint16)
        seed = int((np.abs(chaos_seq[0,0]) * 10**14) % (2**32))
        rng = np.random.default_rng(seed)
        flat = flat[rng.permutation(len(flat))]
        
        # Multi-Dimensional XOR Keys for Bi-directional Diffusion
        kf_raw = (np.abs(chaos_seq[:, 0])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 1])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64)
        kf = np.resize((kf_raw % 256).astype(np.uint16), total)
        cf = np.bitwise_xor.accumulate(np.bitwise_xor(flat, kf))
        
        kb_raw = (np.abs(chaos_seq[:, 2])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 4])*10**14).astype(np.uint64)
        kb = np.resize((kb_raw % 256).astype(np.uint16), total)
        cb = np.bitwise_xor.accumulate(np.bitwise_xor(cf[::-1], kb[::-1]))[::-1]
        
        return cb.astype(np.uint8).reshape(H, W, D), img_hash, seed

    def decrypt_block_pixels_only(self, cipher_flat, img_hash, seed, dims):
        """Symmetric decryption for noise/security tests (No Zstd)"""
        H, W, D = dims
        total = H * W * D
        initial_state = self._derive_keys(img_hash)
        chaos_seq = fast_chaos_engine(max(total, 20000), initial_state, self.params)
        flat_c = cipher_flat.astype(np.uint16)

        # Reverse Backward
        kb_raw = (np.abs(chaos_seq[:, 2])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 4])*10**14).astype(np.uint64)
        kb = np.resize((kb_raw % 256).astype(np.uint16), total)
        shifted_b = np.roll(flat_c, -1); shifted_b[-1] = 0
        dec_b = np.bitwise_xor(np.bitwise_xor(flat_c, shifted_b), kb)
        
        # Reverse Forward
        kf_raw = (np.abs(chaos_seq[:, 0])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 1])*10**14).astype(np.uint64) ^ (np.abs(chaos_seq[:, 3])*10**14).astype(np.uint64)
        kf = np.resize((kf_raw % 256).astype(np.uint16), total)
        shifted_f = np.roll(dec_b, 1); shifted_f[0] = 0
        dec_f = np.bitwise_xor(np.bitwise_xor(dec_b, shifted_f), kf).astype(np.uint8)

        # Reverse Permutation
        rng = np.random.default_rng(seed); perm = rng.permutation(total)
        inv_perm = np.empty_like(perm); inv_perm[perm] = np.arange(total)
        
        return dec_f[inv_perm].reshape(H, W, D)

    # --- PHASE 1 & 4: DATASET PROCESSING & STORAGE ---
    def encrypt_dataset(self, folder_path, batch_size=15):
        valid_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
        if not os.path.exists(folder_path):
            print(f"Error: Folder '{folder_path}' not found."); return

        files = sorted([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.lower().endswith(valid_exts)])
        files.sort(key=lambda x: os.path.getsize(x))
        
        if not files: print("No valid images found."); return

        start_time = time.time(); input_raw_size = 0
        out_dir = f"ProjectVault_{self.vault_id}"
        if not os.path.exists(out_dir): os.makedirs(out_dir)

        manifest = []
        for i in range(0, len(files), batch_size):
            batch_files = files[i : i + batch_size]
            imgs = [cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB) for p in batch_files]
            input_raw_size += sum(img.nbytes for img in imgs)
            
            h_max, w_max = max(m.shape[0] for m in imgs), max(m.shape[1] for m in imgs)
            padded, meta = [], []
            for img in imgs:
                h, w, _ = img.shape; canvas = np.zeros((h_max, w_max, 3), dtype=np.uint8)
                canvas[:h, :w, :] = img; padded.append(canvas); meta.append({'h': h, 'w': w})

            block_3d = np.concatenate(padded, axis=2)
            cipher, b_hash, s_seed = self.encrypt_block(block_3d)
            
            save_path = os.path.join(out_dir, f"r{(i//batch_size)+1}.bin")
            with open(save_path, 'wb') as f: f.write(cipher)
            manifest.append({'id': (i//batch_size)+1, 'hash': b_hash, 'seed': s_seed, 'dims': block_3d.shape, 'meta': meta, 'start': i+1, 'end': i+len(batch_files)})
            print(f"   [Batch] Processing... {i+len(batch_files)}/{len(files)}")

        with open(os.path.join(out_dir, "manifest.pkl"), "wb") as f: pickle.dump(manifest, f)
        
        total_time = time.time() - start_time
        v_size = sum(os.path.getsize(os.path.join(out_dir, f)) for f in os.listdir(out_dir))
        print(f"\n{'='*45}\nRESEARCH PERFORMANCE REPORT\n{'='*45}")
        print(f"Total Execution Time : {total_time:.4f} s")
        print(f"Average Throughput   : {(input_raw_size/(1024**2))/total_time:.4f} MB/s")
        print(f"Efficiency Ratio     : {input_raw_size/v_size:.2f}x (Raw vs Vault)")
        print("="*45)

    def decrypt_images(self, ids_to_decrypt):
        v_dir = f"ProjectVault_{self.vault_id}"
        with open(os.path.join(v_dir, "manifest.pkl"), "rb") as f: manifest = pickle.load(f)
        
        batch_map = {}
        for img_id in ids_to_decrypt:
            target = next((e for e in manifest if e['start'] <= img_id <= e['end']), None)
            if target:
                if target['id'] not in batch_map: batch_map[target['id']] = []
                batch_map[target['id']].append((img_id, target))

        for b_id, tasks in batch_map.items():
            print(f"Decrypting Batch {b_id}...")
            target = tasks[0][1]
            with open(os.path.join(v_dir, f"r{b_id}.bin"), 'rb') as f: cipher = np.frombuffer(f.read(), dtype=np.uint8)
            dec_block = self.decrypt_block(cipher, target['hash'], target['seed'], target['dims'])
            
            for img_id, meta_entry in tasks:
                idx = img_id - meta_entry['start']
                h, w = meta_entry['meta'][idx]['h'], meta_entry['meta'][idx]['w']
                img = dec_block[:h, :w, idx*3 : (idx*3)+3]
                plt.imshow(img); plt.title(f"Image ID: {img_id}"); plt.axis('off'); plt.show()
                cv2.imwrite(f"recovered_img_{img_id}.png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

if __name__ == "__main__":
    print("--- 5D HYPERCHAOTIC RESEARCH PIPELINE ---")
    s_key = input("Enter Secret Key: "); enc = Research5DEncryptor(s_key)
    mode = input("(E)ncrypt Folder or (D)ecrypt Images? ").upper()
    
    if mode == "E":
        target_folder = input("Enter Input Folder Path: ").strip()
        enc.encrypt_dataset(target_folder)
    elif mode == "D":
        v_dir = f"ProjectVault_{enc.vault_id}"
        if not os.path.exists(v_dir): print("Vault not found."); exit()
        with open(os.path.join(v_dir, "manifest.pkl"), "rb") as f: manifest = pickle.load(f)
        total_imgs = manifest[-1]['end']
        print(f"Vault contains {total_imgs} images. Selection Modes: 1. Single 2. Multi 3. All")
        sel = input("Choice: ")
        if sel == "1": ids = [int(input("ID: "))]
        elif sel == "2": ids = [int(x.strip()) for x in input("IDs (1,2,3): ").split(",")]
        else: ids = list(range(1, total_imgs+1))
        enc.decrypt_images(ids)
