"""管理员权限提取微信密钥 - 输出到文件"""
import sys, os

OUT = r"C:\Users\zhzsh\TradingAgents-Astock\wx_key_output.txt"

def log(msg):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

log("=== 微信密钥提取 (管理员模式) ===")

try:
    import pymem, psutil, re
except Exception as e:
    log(f"导入失败: {e}")
    sys.exit(1)

# 找微信主进程
found = False
for p in psutil.process_iter(['name', 'pid', 'exe']):
    if p.info.get('name') == 'Weixin.exe':
        wx_path = str(p.info.get('exe', ''))
        if 'XPlugin' in wx_path:
            continue
        pid = p.info['pid']
        log(f"尝试 PID={pid}")
        try:
            pm = pymem.Pymem(pid)
            mods = pm.list_modules()
            mod_names = [m.name for m in mods]
            if 'WeChatWin.dll' in mod_names:
                log(f"找到 WeChatWin.dll!")
                
                wx_win = [m for m in mods if 'WeChatWin' in m.name][0]
                base = wx_win.lpBaseOfDll
                size = wx_win.SizeOfImage
                log(f"  base=0x{base:X}  size={size/1024/1024:.1f}MB")
                
                # 读取后半部分（.data段通常在后面）
                data_start = base + size // 2
                data_size = min(size // 2, 80 * 1024 * 1024)
                data = pm.read_bytes(data_start, data_size)
                
                # 搜索 64位 hex key
                keys = set()
                for m in re.finditer(rb'[0-9a-fA-F]{64}', data):
                    k = m.group().decode().lower()
                    if len(set(k)) < 5: continue
                    if k[:8] * 8 == k: continue
                    keys.add(k)
                
                log(f"找到 {len(keys)} 个候选密钥")
                
                # 尝试解密 MicroMsg.db
                from sqlcipher3 import dbapi2 as sqlcipher
                db_paths = []
                wx_dir = r"C:\Users\zhzsh\Documents\WeChat Files"
                for d in os.listdir(wx_dir):
                    p = os.path.join(wx_dir, d, "Msg", "MicroMsg.db")
                    if os.path.exists(p):
                        db_paths.append((p, d))
                
                for db_path, wxid in db_paths:
                    log(f"尝试解密: {wxid}/MicroMsg.db ({len(keys)} keys)")
                    found_key = None
                    for i, key in enumerate(list(keys)[:500]):
                        if i % 100 == 0:
                            log(f"  进度: {i}/{min(len(keys),500)}")
                        try:
                            conn = sqlcipher.connect(db_path)
                            conn.execute(f"PRAGMA key=\"x'{key}'\";")
                            conn.execute("PRAGMA cipher_compatibility = 3;")
                            conn.execute("SELECT count(*) FROM sqlite_master;")
                            found_key = key
                            conn.close()
                            break
                        except:
                            continue
                    
                    if found_key:
                        log(f"\n✅ 密钥: {found_key}")
                        with open(r"C:\Users\zhzsh\TradingAgents-Astock\wx_key.txt", "w") as f:
                            f.write(found_key)
                        found = True
                        break
                
                break
        except Exception as e:
            log(f"  PID={pid} 错误: {e}")
            continue

if not found:
    log("\n❌ 未找到密钥")
else:
    log("\n✅ 密钥已保存到 wx_key.txt")

log("\n=== 完成 ===")
