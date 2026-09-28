"""客户端本地密钥保管：用 Windows DPAPI 加密要保存的密码。

为什么不用明文：客户端目录里的 `client_config.json` 是纯文本，谁都能打开看。
如果直接写明文密码，等于把账号送给任何一个能碰到这台电脑的人。

Windows 的 DPAPI（CryptProtectData）会用**当前 Windows 用户的凭据**加密，
密文只能在同一个用户账户下解开 —— 把文件拷到别的机器、别的账号都解不开。

拿不到 DPAPI 时（非 Windows / 调用失败）就**什么都不存**：宁可每次手输密码，
也不把明文密码写进文件。
"""
import base64
import ctypes
import sys

MAGIC = 'dpapi1:'          # 存在配置里的前缀，用来识别格式
_ENTROPY = b'qiaoni-social-client'   # 固定熵：让密文只对本程序有意义

__all__ = ['protect', 'unprotect', 'available']


class _BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32),
                ('pbData', ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    """把 bytes 包成 DATA_BLOB（返回值要留着引用，否则缓冲区会被回收）。"""
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt32():
    if not sys.platform.startswith('win'):
        return None
    try:
        return ctypes.windll.crypt32
    except Exception:
        return None


def available():
    """这台机器上能不能用 DPAPI。"""
    return _crypt32() is not None


def protect(text):
    """加密一段文本 → 'dpapi1:base64'；失败返回 ''（调用方就当没保存）。"""
    if not text:
        return ''
    api = _crypt32()
    if api is None:
        return ''
    out = _BLOB()
    try:
        data = str(text).encode('utf-8')
        inb, _keep1 = _blob(data)
        ent, _keep2 = _blob(_ENTROPY)
        ok = api.CryptProtectData(ctypes.byref(inb), None, ctypes.byref(ent),
                                  None, None, 0x1,  # CRYPTPROTECT_UI_FORBIDDEN
                                  ctypes.byref(out))
        if not ok or not out.pbData:
            return ''
        raw = ctypes.string_at(out.pbData, out.cbData)
        return MAGIC + base64.b64encode(raw).decode('ascii')
    except Exception:
        return ''
    finally:
        try:
            if out.pbData:
                ctypes.windll.kernel32.LocalFree(out.pbData)
        except Exception:
            pass


def unprotect(token):
    """解密 protect() 的产物；失败/格式不对返回 ''。"""
    if not token or not isinstance(token, str) or not token.startswith(MAGIC):
        return ''
    api = _crypt32()
    if api is None:
        return ''
    out = _BLOB()
    try:
        raw = base64.b64decode(token[len(MAGIC):])
        inb, _keep1 = _blob(raw)
        ent, _keep2 = _blob(_ENTROPY)
        ok = api.CryptUnprotectData(ctypes.byref(inb), None, ctypes.byref(ent),
                                    None, None, 0x1,
                                    ctypes.byref(out))
        if not ok or not out.pbData:
            return ''
        return ctypes.string_at(out.pbData, out.cbData).decode('utf-8', 'replace')
    except Exception:
        return ''
    finally:
        try:
            if out.pbData:
                ctypes.windll.kernel32.LocalFree(out.pbData)
        except Exception:
            pass


if __name__ == '__main__':
    # 自检：能加能解、密文里不含明文、换熵解不开
    print('DPAPI 可用:', available())
    secret = 'my-pass-1234'
    tok = protect(secret)
    print('密文前缀:', tok[:16], '长度:', len(tok))
    assert tok and secret not in tok, '密文里不应该出现明文'
    assert unprotect(tok) == secret, '必须能解回原文'
    assert unprotect(tok[:-4] + 'AAAA') == '', '改坏了就应该解不开'
    assert unprotect('') == '' and unprotect('plain:xxx') == ''
    print('SELFTEST_OK')
