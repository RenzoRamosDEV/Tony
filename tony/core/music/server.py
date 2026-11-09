from mcp.server.mcpserver import MCPServer

from tony.core.music.player import MusicPlayer


def build_server(player: MusicPlayer) -> MCPServer:
    server = MCPServer("music")

    @server.tool(description="Busca una canción y dice su título sin reproducirla.")
    def music_search(consulta: str) -> str:
        return player.search(consulta)

    @server.tool(description="Busca una canción y la reproduce, sustituyendo lo que suene.")
    def music_play(consulta: str) -> str:
        return player.play(consulta)

    @server.tool(description="Busca una canción y la añade al final de la cola.")
    def music_queue(consulta: str) -> str:
        return player.queue(consulta)

    @server.tool(description="Pausa la reproducción.")
    def music_pause() -> str:
        return player.pause()

    @server.tool(description="Reanuda la reproducción pausada.")
    def music_resume() -> str:
        return player.resume()

    @server.tool(description="Pasa a la siguiente canción de la cola.")
    def music_next() -> str:
        return player.next()

    @server.tool(description="Vuelve a la canción anterior de la cola.")
    def music_previous() -> str:
        return player.previous()

    @server.tool(description="Ajusta el volumen, de 0 a 100.")
    def music_volume(nivel: int) -> str:
        return player.set_volume(nivel)

    @server.tool(description="Dice qué suena: título, pausa, volumen y posición.")
    def music_now_playing() -> str:
        return player.now_playing()

    @server.tool(description="Detiene la música y vacía la cola.")
    def music_stop() -> str:
        return player.stop()

    return server
