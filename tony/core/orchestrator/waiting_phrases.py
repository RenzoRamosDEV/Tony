import random
from collections.abc import Callable, Sequence

ORIGINAL_PHRASE = "Un momento, señor; estoy en ello."

WAITING_PHRASES: tuple[str, ...] = (
    "Un momento, señor; estoy en ello.",
    "Permítame un instante, señor.",
    "Estoy en ello, señor.",
    "Un segundo, señor; trabajo en ello.",
    "Con su permiso, señor, sigo en ello.",
    "Paciencia, señor; el asunto está en marcha.",
    "Sigo en ello, señor; sin sobresaltos.",
    "Estoy en ello, señor; no me he ido.",
    "Un instante, señor; los bits no se mueven solos.",
    "Trabajando en ello, señor.",
    "Démelo un momento, señor.",
    "Enseguida sigo con ello, señor.",
    "Estoy ocupándome, señor.",
    "Permítame unos instantes más, señor.",
    "Siga conmigo, señor; esto lleva su tiempo.",
    "Un instante más, señor, se lo ruego.",
    "Tenga a bien esperar un momento, señor.",
    "Sigo con ello, señor; sin prisa pero sin pausa.",
    "Ya me estoy encargando, señor.",
    "Un instante, señor; la rapidez es una virtud relativa.",
    "Aún estoy en ello, señor.",
    "Dé un respiro a este humilde mayordomo, señor.",
    "Estoy en plena faena, señor.",
    "Con calma, señor; ya me ocupo.",
    "Un momentito, señor.",
    "Señor, sigo trabajando en ello.",
    "Permítame terminar, señor.",
    "Todavía en ello, señor; gracias por la paciencia.",
    "Esto requiere un instante, señor.",
    "Prosigo con el encargo, señor.",
    "Me pongo a ello, señor; un momento.",
    "Estoy en ello, señor; sírvase esperar.",
    "Un poco de paciencia, señor, se lo suplico.",
    "El encargo sigue su curso, señor.",
    "Sigo ocupado con ello, señor.",
    "Un momento, señor; no he olvidado su encargo.",
    "Permítame un momento más, señor.",
    "Aún trabajo en ello, señor.",
    "Disculpe la espera, señor; sigo en ello.",
    "Sigo en la brecha, señor.",
    "Atiendo su encargo, señor; un instante.",
    "Sigo a su servicio, señor; un momento.",
    "Un instante, señor; la diligencia lleva su tiempo.",
    "Estoy en ello, señor; no se impaciente.",
    "Lo estoy atendiendo, señor.",
    "Concédame un momento, señor.",
    "Sigo en el asunto, señor.",
    "Un momento de gracia, señor.",
    "Permanezca a la espera, señor; sigo en ello.",
    "Un instante, señor; la perfección requiere tiempo.",
)

Chooser = Callable[[Sequence[str]], str]


class WaitingPhrases:
    """Picks a waiting phrase at random, never the one picked just before."""

    def __init__(self, choose: Chooser = random.choice) -> None:
        self._choose = choose
        self._last: str | None = None

    def next(self) -> str:
        candidates = tuple(p for p in WAITING_PHRASES if p != self._last)
        self._last = self._choose(candidates)
        return self._last
