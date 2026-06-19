import io
import os
import stat
import time
import paramiko
from PyQt6.QtCore import QThread, pyqtSignal


def _list_recursive(sftp, remote_path: str, depth: int = 0) -> list:
    """Retourne l'arborescence sous remote_path comme liste de dicts."""
    if depth > 6:
        return []
    entries = []
    try:
        attrs = sftp.listdir_attr(remote_path)
    except Exception:
        return []
    for attr in attrs:
        is_dir = stat.S_ISDIR(attr.st_mode or 0)
        entry = {
            'name': attr.filename,
            'path': remote_path.rstrip('/') + '/' + attr.filename,
            'is_dir': is_dir,
            'size': attr.st_size or 0,
            'children': [],
        }
        if is_dir:
            entry['children'] = _list_recursive(sftp, entry['path'], depth + 1)
        entries.append(entry)
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    return entries


class SftpConnectWorker(QThread):
    """Connexion SSH/SFTP et listing récursif du dossier distant (thread séparé)."""

    connected = pyqtSignal(list)   # arborescence d'entrées distantes
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str, remote_dir: str):
        super().__init__()
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.remote_dir = remote_dir

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            entries = _list_recursive(sftp, self.remote_dir)
            sftp.close()
            self.connected.emit(entries)
        except paramiko.AuthenticationException:
            self.error.emit("Échec d'authentification — identifiant ou mot de passe incorrect.")
        except paramiko.SSHException as e:
            self.error.emit(f"Erreur SSH : {e}")
        except OSError as e:
            self.error.emit(f"Impossible de joindre {self.ip}:{self.port} — {e}")
        except Exception as e:
            self.error.emit(f"Erreur inattendue : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SftpDownloadWorker(QThread):
    """Téléchargement SFTP des fichiers sélectionnés vers un dossier local (thread séparé)."""

    # file_idx, file_total, filename, file_bytes_done, file_bytes_total,
    # total_bytes_done, total_bytes_all, speed_bps
    progress = pyqtSignal(int, int, str, int, int, int, int, float)
    finished = pyqtSignal(int, int)   # fichiers téléchargés, octets totaux
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str,
                 remote_files: list, local_base: str, remote_base: str):
        super().__init__()
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.remote_files = remote_files
        self.local_base = local_base
        self.remote_base = remote_base.rstrip('/')

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            total_files = len(self.remote_files)

            # Récupère les tailles de tous les fichiers d'abord
            file_sizes = {}
            for rp in self.remote_files:
                try:
                    file_sizes[rp] = sftp.stat(rp).st_size or 0
                except Exception:
                    file_sizes[rp] = 0
            total_size = sum(file_sizes.values())

            total_done_ref = [0]
            last_emit_ref  = [0.0]
            start_time     = time.monotonic()
            downloaded     = 0

            for i, remote_path in enumerate(self.remote_files):
                if self.isInterruptionRequested():
                    break

                filename  = os.path.basename(remote_path)
                file_size = file_sizes[remote_path]
                rel        = remote_path[len(self.remote_base):].lstrip('/')
                local_path = os.path.join(self.local_base, rel.replace('/', os.sep))
                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                # Émission initiale (0 octet transféré pour ce fichier)
                self.progress.emit(i, total_files, filename,
                                   0, file_size,
                                   total_done_ref[0], total_size, 0.0)

                prev_bytes = [0]

                def _cb(bt_done, bt_total,
                        _i=i, _fname=filename, _fsize=file_size,
                        _prev=prev_bytes):
                    delta = bt_done - _prev[0]
                    _prev[0] = bt_done
                    total_done_ref[0] += delta
                    now = time.monotonic()
                    if now - last_emit_ref[0] >= 0.08:   # ~12 Hz max
                        elapsed = now - start_time
                        speed = total_done_ref[0] / elapsed if elapsed > 0.1 else 0.0
                        self.progress.emit(_i, total_files, _fname,
                                           bt_done, bt_total,
                                           total_done_ref[0], total_size, speed)
                        last_emit_ref[0] = now

                sftp.get(remote_path, local_path, callback=_cb)
                # Garantit le compte exact après chaque fichier complet
                total_done_ref[0] = sum(file_sizes[p]
                                        for p in self.remote_files[:i + 1])
                downloaded += 1

            sftp.close()
            self.finished.emit(downloaded, total_done_ref[0])
        except paramiko.AuthenticationException:
            self.error.emit("Échec d'authentification lors du téléchargement.")
        except Exception as e:
            self.error.emit(f"Erreur de transfert : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SftpUploadWorker(QThread):
    """Envoi d'un fichier (bytes) vers un chemin distant via SFTP (thread séparé)."""

    finished = pyqtSignal(str)   # chemin distant effectif
    error    = pyqtSignal(str)

    def __init__(self, ip: str, port: int, user: str, password: str,
                 remote_path: str, data: bytes):
        super().__init__()
        self.ip          = ip
        self.port        = port
        self.user        = user
        self.password    = password
        self.remote_path = remote_path
        self.data        = data

    def run(self):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.password, timeout=10)
            sftp = ssh.open_sftp()
            # Créer les dossiers parents si nécessaire
            remote_dir = self.remote_path.rsplit('/', 1)[0]
            if remote_dir:
                try:
                    sftp.makedirs = None   # paramiko n'a pas makedirs
                    parts = remote_dir.lstrip('/').split('/')
                    current = '/' if remote_dir.startswith('/') else ''
                    for part in parts:
                        current = (current + '/' + part).replace('//', '/')
                        try:
                            sftp.stat(current)
                        except IOError:
                            sftp.mkdir(current)
                except Exception:
                    pass
            with sftp.file(self.remote_path, 'wb') as f:
                f.write(self.data)
            sftp.close()
            self.finished.emit(self.remote_path)
        except paramiko.AuthenticationException:
            self.error.emit("Echec d'authentification — identifiant ou mot de passe incorrect.")
        except paramiko.SSHException as e:
            self.error.emit(f"Erreur SSH : {e}")
        except OSError as e:
            self.error.emit(f"Impossible de joindre {self.ip}:{self.port} — {e}")
        except Exception as e:
            self.error.emit(f"Erreur inattendue : {e}")
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass
