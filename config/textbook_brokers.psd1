@{
    Connection = @{
        Protocol = "Sftp"
        HostName = "sftp.textbooktech.com"
        PortNumber = 22
        UserName = "mines"

        PrivateKeyDirectory = "privatekeys"
        PrivateKeyFileName  = "id_rsa.ppk"

        HostKeyFingerprint = "ssh-ed25519 255 xx3gST/JDsRuRP2aztHEBqYqVbzaoqySJN7Svx5Fswg"
    } 

    Remote = @{
        SourceDirectory = "/accounts"

        Finaid = @{
            FilePattern       = "finaid_*.csv"
            CompletedDirectory = "/accounts/Processed by Mines/Finaid/{TermCode} {TermName}"
        }

        IA = @{
            FilePattern       = "ia_*.csv"
            CompletedDirectory = "/accounts/Processed by Mines/IA/{TermCode} {TermName}"
        }
    }

    Local = @{
        RootEnvironmentVariable = "OneDriveCommercial"
        BusinessDirectory       = "GRP-Bursar Office - General\Y-IS(Shared) - Banner Student AR\BOOK"
        TermDirectoryPattern    = "{TermCode}"

        CompletedSourceDirectory = "archive\source"

        OutputDirectory = "output"
        OutputFileName  = "TSPLOAD.csv"

        UploadedDirectory       = "archive\uploaded"
        UploadedFileNamePattern = "TSPLOAD_{DateTime}.csv"

        ErrorDirectory = "error"
    }

    Logging = @{
        Directory = "logs\textbook_brokers"
    }
}