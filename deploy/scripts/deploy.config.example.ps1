# Copia este archivo como deploy.config.ps1 (esta ignorado por git) y ajusta los valores.
$Servidor     = "andana@193.43.134.86"      # usuario@IP del VPS de Hostinger
$Dominio      = "zeolitas.forasoft.cloud"            # el DNS (registro A) debe apuntar a la IP del VPS
$LlaveSsh     = ""                          # ruta a tu llave privada, o vacio para usar la predeterminada
$FrontendDir  = "C:\Users\luis_\ftir-zeolitas-uas"
$BaseDeDatosLocal = "ftir_zeolitas"
$UsuarioMysqlLocal = "root"
$HostMysqlLocal = "localhost"
