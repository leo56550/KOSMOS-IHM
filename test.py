import paramiko
import os

# --- CONFIGURATION ---
RPI_IP = "192.168.10.2"      # Remplacez par l'IP de votre Raspberry Pi
RPI_USER = "kosmos"             # Votre nom d'utilisateur (ex: pi ou autre)
RPI_PASSWORD = "kosmos"   # Votre mot de passe SSH
REMOTE_DIR = "kosmos_local_sd"    # Le dossier à explorer sur la Raspberry Pi
# ---------------------

def test_sftp_connection():
    ssh = None
    try:
        print(f"Connexion en cours à {RPI_IP}...")
        
        # 1. Initialisation du client SSH
        ssh = paramiko.SSHClient()
        # Permet d'accepter automatiquement la clé SSH de la Raspberry au premier essai
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 2. Connexion au serveur
        ssh.connect(RPI_IP, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
        print(" Connexion SSH réussie !")

        # 3. Ouverture de la session SFTP
        sftp = ssh.open_sftp()
        print(" Session SFTP ouverte avec succès.\n")

        # 4. Lecture du contenu du dossier
        print(f"Contenu du dossier '{REMOTE_DIR}' :")
        files = sftp.listdir(REMOTE_DIR)
        
        if not files:
            print("  (Le dossier est vide)")
        for file in files:
            print(f" - {file}")

        # 5. Fermeture des connexions
        sftp.close()
        print("\n Déconnexion réussie.")

    except paramiko.AuthenticationException:
        print("\n Erreur : Échec d'authentification. Vérifiez l'identifiant ou le mot de passe.")
    except paramiko.SSHException as ssh_err:
        print(f"\n Erreur SSH : {ssh_err}")
    except Exception as e:
        print(f"\n Erreur de connexion : {e}")
        print("Vérifiez que la Raspberry est bien sur le même réseau WiFi et que le SSH est activé.")
    finally:
        if ssh:
            ssh.close()

if __name__ == "__main__":
    test_sftp_connection()