import os
import stat
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

    progress = pyqtSignal(int, int, str)   # index courant, total, nom du fichier
    finished = pyqtSignal(int)             # nombre de fichiers téléchargés
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
            total = len(self.remote_files)
            downloaded = 0
            for i, remote_path in enumerate(self.remote_files):
                if self.isInterruptionRequested():
                    break
                rel = remote_path[len(self.remote_base):].lstrip('/')
                local_path = os.path.join(self.local_base,
                                          rel.replace('/', os.sep))
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                self.progress.emit(i, total, os.path.basename(remote_path))
                sftp.get(remote_path, local_path)
                downloaded += 1
            sftp.close()
            self.finished.emit(downloaded)
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
