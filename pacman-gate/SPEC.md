# SPEC — Mobile-first Pac-Man (single self-contained HTML file)

Build `pacman.html`, one file, inline CSS+JS, no external assets, no libraries.

## Gameplay (classic, complete)
- Grid maze ≥ 20×20 with dots (10 pts) and 4 corner power pellets (50 pts). >50 dots total.
- Pac-Man: continuous movement cell-to-cell; direction changes queued (nextDir) and applied at any
  cell where the turn is walkable. Keyboard arrows AND touch swipe (swipe anywhere, threshold ~30px).
- 4 ghosts with classic personalities: blinky targets pacman; pinky targets 4 ahead; inky uses
  blinky-reflection; clyde chases far / scatters near. Ghosts CHASE — decision at EVERY cell step:
  pick the walkable non-reverse direction minimizing distance to target; if none, reverse. No
  parity/"intersection" heuristics.
- Ghost house: blinky starts outside; pinky/inky/clyde exit after 1s / 3s / 5s. Eaten ghosts
  respawn in house, exit after 3s.
- Power mode: 7 seconds, ghosts frightened (blue, flee = target their scatter corner), eaten ghost
  = 200×2^combo. Timer visibly runs out (blink last 2s).
- Collisions must ALSO detect cell-swap (pacman and ghost exchanging cells in one step).
- Death: lives 3, respawn pacman + ghosts, 1s pause. 0 lives = GAME OVER overlay. All dots eaten =
  YOU WIN overlay. Both overlays: final score + PLAY AGAIN working via touch AND click.

## Engineering constraints (hard rules — these caused real bugs before)
- Fixed-timestep logic loop (accumulator over requestAnimationFrame). EVERY duration constant must
  be derived in SECONDS via the timestep (e.g. `const TICKS = s => Math.round(s*1000/MOVE_INTERVAL)`),
  never raw frame counts.
- Smooth motion: render-interpolate every entity between previous and current cell using the
  accumulator fraction. Initialize prev fields AT CREATION and reset them on every teleport
  (house exit, respawn, death reset). Skip interpolation on tunnel wrap.
- Start screen: PLAY must work via BOTH click and touch (guard double-fire). touch-action:none;
  preventDefault so swipes never scroll. Canvas scales to phone width (max-width:100vw, aspect kept).
- No invented browser/canvas APIs.

## Testability contract (the gate depends on this — build will FAIL without it)
- Game state as TOP-LEVEL `let`: pacman, ghosts, maze, score, lives, powerMode, gameState,
  dotCount, totalDots. Core functions as TOP-LEVEL `function` declarations: movePacman,
  moveGhost, checkGhostCollisions, startGame.
- pacman/ghost objects: x,y = current CELL; prev = {x,y} previous cell.
- maze values: 0 empty, 1 wall, 2 dot, 3 power pellet (house tiles may use other values).
