# AndreyCloud

Sua nuvem pessoal que roda **localmente no seu PC**. Gratuita e open source.

Interface escura, estilo "Drive", feita com PyQt6. Os arquivos ficam em pastas normais do seu computador: nada vai para servidor de terceiros.

> ⚠️ **Projeto em fase inicial.** O app move, renomeia e apaga arquivos. Teste primeiro com arquivos sem importância e mantenha backup do que é valioso.

<!-- Coloque aqui um print da janela, por exemplo: ![AndreyCloud](docs/screenshot.png) -->

## Recursos

- **Vários discos/partições:** você escolhe quais discos usar (C:, D:, pendrives…). O app cria a pasta `AndreyCloud` dentro de cada um e **soma o espaço livre** de todos. Dá para mudar a escolha quando quiser em *Configurações*.
- Upload por botão ou arrastando e soltando (arquivos e pastas), com barra de progresso e cancelamento.
- Pastas, renomear, mover (inclusive entre discos), favoritos e busca.
- **Lixeira** com restauração (cada disco tem a sua).
- **Selecionar tudo** e exclusão em lote.
- Miniaturas de imagens e filtros por tipo (Documentos, Imagens, Vídeos, Compactados…).
- **Compartilhamento na rede local:** cria um link acessível por outros dispositivos na mesma rede Wi-Fi/LAN, enquanto o app estiver aberto.
- Você também pode mexer nas pastas pelo Explorador de Arquivos: o app atualiza sozinho quando você volta para a janela (ou aperte `F5`).
- Tudo é desenhado via `QPainter` (ícones, pastas, miniaturas): não depende de imagens externas.

## Instalação

### Windows (executável)

Baixe o `.exe` mais recente na página de **[Releases](../../releases)** e execute.

> O Windows SmartScreen e alguns antivírus costumam alertar sobre executáveis gerados com Nuitka/PyInstaller (falso positivo). Se preferir não confiar no `.exe`, rode pelo código-fonte, como abaixo.

### Pelo código-fonte (Windows, Linux, macOS)

Requer Python 3.9+.

```bash
pip install -r requirements.txt
python andreycloud.py
```

Na primeira execução o app pede para você escolher os discos que quer usar.

## Atalhos

| Atalho | Ação |
| --- | --- |
| `Ctrl+F` | Buscar |
| `Ctrl+A` | Selecionar tudo |
| `F2` | Renomear |
| `Delete` | Mover para a lixeira |
| `F5` | Atualizar |
| `Alt+←` | Voltar uma pasta |

Duplo clique abre pastas e arquivos.

## Onde ficam os dados

- **Seus arquivos:** na pasta `AndreyCloud` de cada disco escolhido (ex.: `C:\AndreyCloud`, `D:\AndreyCloud`). Se o app não puder criar a pasta na raiz do disco (comum no Linux/macOS), ele usa `~/AndreyCloud` quando sua pasta de usuário estiver nesse disco.
- **Configurações:** `~/.andreycloud/config.json`
- **Favoritos, links e itens da lixeira:** `~/.andreycloud/meta.json`
- **Foto de perfil:** pelo menu do perfil, ou coloque um `avatar.png` em `~/.andreycloud/`.

Desmarcar um disco nas configurações só o esconde do app: os arquivos dele continuam na pasta e voltam quando você marcá-lo de novo.

## Segurança do compartilhamento

- O link funciona por **HTTP, sem senha e sem criptografia**: qualquer pessoa na sua rede que tiver o link consegue baixar o item. O endereço contém um código aleatório difícil de adivinhar, mas trate-o como segredo.
- Só funciona enquanto o app estiver aberto e apenas na rede local. Para acessar de fora de casa, use uma VPN (como o Tailscale) em vez de abrir portas no roteador.
- Dá para encerrar o compartilhamento de um item a qualquer momento (*Compart.* → *Parar de compartilhar*).

## Gerar o executável (Nuitka)

```bash
pip install nuitka
python -m nuitka --onefile --enable-plugin=pyqt6 --windows-console-mode=disable andreycloud.py
```

(Em versões antigas do Nuitka, use `--windows-disable-console` no lugar de `--windows-console-mode=disable`.)

## Licença

Distribuído sob a **GNU GPL v3**. Veja o arquivo [LICENSE](LICENSE). O projeto usa o PyQt6, que também é licenciado sob GPL v3.
