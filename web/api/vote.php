<?php
// fACTUAL reader polls. GET ?poll=<id>&n=<answers> reads a poll; POST {poll, n, choice} votes.
// One vote per device (a cookie the server sets) and at most MAX_PER_NETWORK per network address, which is
// generous on purpose: phone carriers put thousands of people behind one address. A poll opens on its first
// view and takes votes for 24 hours; after that, results only. Counts are shown only to someone who has
// voted, or once voting has closed. Network addresses are stored only as salted hashes.
declare(strict_types=1);
ini_set('display_errors', '0');
ob_start();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
register_shutdown_function(function () {
    $e = error_get_last();
    if ($e && in_array($e['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR], true)) {
        ob_end_clean();
        http_response_code(500);
        echo json_encode(['error' => 'server']);
    }
});

const VERSION = '1';
const OPEN_SECONDS = 86400;
const MAX_PER_NETWORK = 40;

function reply(array $body, int $code = 200): void {
    ob_end_clean();
    http_response_code($code);
    echo json_encode($body);
    exit;
}

if (($_GET['v'] ?? '') === '1') reply(['ok' => true, 'version' => VERSION]);

$post = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST';
$in = $post ? (json_decode((string) file_get_contents('php://input'), true) ?: []) : $_GET;
$poll = (string) ($in['poll'] ?? '');
$n = (int) ($in['n'] ?? 0);
if (!preg_match('/^[a-f0-9]{6,16}-[a-f0-9]{8}$/', $poll) || $n < 2 || $n > 6) reply(['error' => 'bad request'], 400);

$dir = __DIR__ . '/store';
if (!is_dir($dir)) mkdir($dir, 0700, true);
$db = new PDO('sqlite:' . $dir . '/polls.sqlite');
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$db->exec('PRAGMA busy_timeout = 4000');
$db->exec('CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY, answers INTEGER NOT NULL, opened INTEGER NOT NULL)');
$db->exec('CREATE TABLE IF NOT EXISTS votes (poll TEXT NOT NULL, voter TEXT NOT NULL, net TEXT NOT NULL, choice INTEGER NOT NULL, at INTEGER NOT NULL, PRIMARY KEY (poll, voter))');
$db->exec('CREATE INDEX IF NOT EXISTS votes_net ON votes (poll, net)');

$saltFile = $dir . '/salt';
if (!is_file($saltFile)) file_put_contents($saltFile, bin2hex(random_bytes(32)), LOCK_EX);
// The host's CDN passes the reader's own address as REMOTE_ADDR (checked 2026-10-19). An IPv6 device
// changes its address within its network's /64, so IPv6 counts by that prefix.
$addr = (string) ($_SERVER['REMOTE_ADDR'] ?? '');
if (filter_var($addr, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) $addr = bin2hex(substr((string) inet_pton($addr), 0, 8)) . '::/64';
$net = hash('sha256', trim((string) file_get_contents($saltFile)) . '|' . $addr);

// The device: a random id in an HttpOnly cookie, set on first visit.
$voter = (string) ($_COOKIE['fx_voter'] ?? '');
if (!preg_match('/^[a-f0-9]{32}$/', $voter)) {
    $voter = bin2hex(random_bytes(16));
    $https = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    $site = rtrim(dirname(dirname($_SERVER['SCRIPT_NAME'] ?? '/api/vote.php')), '/') . '/';  // the site's folder
    setcookie('fx_voter', $voter, ['expires' => time() + 60 * 60 * 24 * 400, 'path' => $site, 'secure' => $https, 'httponly' => true, 'samesite' => 'Lax']);
}

$now = time();
$get = $db->prepare('SELECT answers, opened FROM polls WHERE id = ?');
$get->execute([$poll]);
$p = $get->fetch(PDO::FETCH_ASSOC);
if (!$p) {
    // A poll exists only if a scan wrote it: its id must be in the live stories file.
    $live = @file_get_contents(__DIR__ . '/../data/stories.json');
    if ($live === false || strpos($live, '"' . $poll . '"') === false) reply(['error' => 'no such poll'], 404);
    $db->prepare('INSERT OR IGNORE INTO polls (id, answers, opened) VALUES (?, ?, ?)')->execute([$poll, $n, $now]);
    $get->execute([$poll]);
    $p = $get->fetch(PDO::FETCH_ASSOC);
}
$answers = (int) $p['answers'];
$closes = (int) $p['opened'] + OPEN_SECONDS;
$open = $now < $closes;

function mine(PDO $db, string $poll, string $voter): ?int {
    $q = $db->prepare('SELECT choice FROM votes WHERE poll = ? AND voter = ?');
    $q->execute([$poll, $voter]);
    $c = $q->fetchColumn();
    return $c === false ? null : (int) $c;
}

function state(PDO $db, string $poll, int $answers, int $closes, bool $open, ?int $mine): array {
    $out = ['open' => $open, 'closes' => $closes, 'mine' => $mine];
    if ($mine !== null || !$open) {
        $counts = array_fill(0, $answers, 0);
        $q = $db->prepare('SELECT choice, COUNT(*) FROM votes WHERE poll = ? GROUP BY choice');
        $q->execute([$poll]);
        foreach ($q->fetchAll(PDO::FETCH_NUM) as [$c, $k]) if ($c >= 0 && $c < $answers) $counts[(int) $c] = (int) $k;
        $out['counts'] = $counts;
        $out['total'] = array_sum($counts);
    }
    return $out;
}

$had = mine($db, $poll, $voter);
if (!$post) reply(state($db, $poll, $answers, $closes, $open, $had));

$choice = (int) ($in['choice'] ?? -1);
if ($choice < 0 || $choice >= $answers) reply(['error' => 'bad choice'], 400);
if ($had !== null) reply(state($db, $poll, $answers, $closes, $open, $had) + ['error' => 'already voted'], 409);
if (!$open) reply(state($db, $poll, $answers, $closes, $open, null) + ['error' => 'closed'], 409);
$c = $db->prepare('SELECT COUNT(*) FROM votes WHERE poll = ? AND net = ?');
$c->execute([$poll, $net]);
if ((int) $c->fetchColumn() >= MAX_PER_NETWORK) reply(['error' => 'too many votes from this network'], 429);
$db->prepare('INSERT OR IGNORE INTO votes (poll, voter, net, choice, at) VALUES (?, ?, ?, ?, ?)')->execute([$poll, $voter, $net, $choice, $now]);
reply(state($db, $poll, $answers, $closes, $open, mine($db, $poll, $voter)));
