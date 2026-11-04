<?php
// U.S. House and Senate seats won, for the Elections section's seat charts (Heston, 2026-11-04: "stories about the
// house and senate, with diagrams/data viz about the seats won"). The AP's own data is paid; Wikipedia's election
// pages gather the AP's and the networks' calls within minutes, and he agreed to use them with these safeguards:
//  - we show the page as it stood 15 minutes ago, never the newest edit, so vandalism has time to be reverted;
//  - the newest edit must not contradict it (no party's called seats falling by more than 2), or we keep the last
//    copy we showed and say the numbers are settling;
//  - impossible counts (more than 435 House seats, a Senate grid without exactly 100 seats) are never shown.
// Read at most every 5 minutes, however many readers. Says where the numbers came from and as of when.
declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
set_time_limit(60);

const API = 'https://en.wikipedia.org/w/api.php';
const UA = 'fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)';
const PAGES = ['house' => '2026_United_States_House_of_Representatives_elections', 'senate' => '2026_United_States_Senate_elections'];
const EVERY = 300;     // seconds between reads
const STAND = 900;     // a revision must have stood this long to be shown
const SLACK = 2;       // how far a party's called seats may fall between the shown revision and the newest

$dir = __DIR__ . '/store';
if (!is_dir($dir)) mkdir($dir, 0700, true);
$cache = "$dir/seats.json";
$age = is_file($cache) ? time() - filemtime($cache) : PHP_INT_MAX;
if ($age >= EVERY) {
    $lock = fopen("$dir/seats.lock", 'c');
    if ($lock && flock($lock, LOCK_EX | LOCK_NB)) {
        clearstatcache();
        if (!is_file($cache) || time() - filemtime($cache) >= EVERY) {
            $last = is_file($cache) ? json_decode((string) file_get_contents($cache), true) : null;
            $out = read_all(is_array($last) ? $last : null);
            if ($out) file_put_contents("$cache.tmp", json_encode($out)) && rename("$cache.tmp", $cache);
            else @touch($cache);
        }
        flock($lock, LOCK_UN);
    }
}
$body = is_file($cache) ? (string) file_get_contents($cache) : '';
$res = $body ? json_decode($body, true) : null;
if (!is_array($res)) { echo json_encode(['ok' => false]); exit; }
$res['checked_at'] = gmdate('c', (int) filemtime($cache));
echo json_encode($res);

function get(string $url): ?string {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20, CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_USERAGENT => UA, CURLOPT_ENCODING => '']);
    $b = curl_exec($ch);
    return ($b !== false && curl_getinfo($ch, CURLINFO_HTTP_CODE) === 200) ? $b : null;
}
function api(array $q): ?array {
    $raw = get(API . '?' . http_build_query($q + ['format' => 'json', 'formatversion' => '2']));
    $d = $raw ? json_decode($raw, true) : null;
    return is_array($d) ? $d : null;
}
// The newest revision and the newest one that has stood STAND seconds: [[id, time], [id, time]].
function revisions(string $title): ?array {
    $d = api(['action' => 'query', 'prop' => 'revisions', 'titles' => $title, 'rvlimit' => 50, 'rvprop' => 'ids|timestamp']);
    $revs = $d['query']['pages'][0]['revisions'] ?? null;
    if (!$revs) return null;
    $now = [$revs[0]['revid'], $revs[0]['timestamp']];
    foreach ($revs as $r) if (time() - strtotime($r['timestamp']) >= STAND) return [$now, [$r['revid'], $r['timestamp']]];
    return null;  // every recent revision is newer than STAND: nothing has stood long enough yet
}
function wikitext(int $revid): ?string {
    $d = api(['action' => 'query', 'prop' => 'revisions', 'revids' => $revid, 'rvprop' => 'content', 'rvslots' => 'main']);
    return $d['query']['pages'][0]['revisions'][0]['slots']['main']['content'] ?? null;
}
function field(string $w, string $k): string {
    return preg_match('/\|\s*' . preg_quote($k, '/') . '\s*=\s*([^\n|]*)/', $w, $m) ? trim($m[1]) : '';
}
function num(string $v): ?int { $v = preg_replace("/'''|''/", '', $v); return preg_match('/^\s*(\d+)\s*$/', $v, $m) ? (int) $m[1] : null; }
function party(string $p): string {
    return stripos($p, 'Democratic') !== false ? 'D' : (stripos($p, 'Republican') !== false ? 'R' : (stripos($p, 'Independent') !== false ? 'I' : '?'));
}

// House: the infobox's seats won so far, party by party. Seats not yet called are the rest of the 435.
function house(string $w): ?array {
    $won = ['D' => 0, 'R' => 0, 'other' => 0];
    for ($i = 1; $i <= 4; $i++) {
        $p = field($w, "party$i");
        if ($p === '') continue;
        $n = num(field($w, "seats$i"));
        if ($n === null) $n = num(field($w, "seats_after$i"));
        if ($n === null) continue;
        $k = party($p);
        $won[$k === 'D' || $k === 'R' ? $k : 'other'] += $n;
    }
    $called = $won['D'] + $won['R'] + $won['other'];
    if ($called > 435 || $won['D'] + $won['R'] === 0) return null;
    return ['D' => $won['D'], 'R' => $won['R'], 'other' => $won['other'], 'uncalled' => 435 - $called, 'total' => 435, 'majority' => 218,
        'page_updated' => preg_replace('/\[\[|\]\]/', '', field($w, 'last_update'))];
}

// Senate: the "After the elections" seat grid, one cell per seat: its party, whether it was up this year, the state,
// and the result ("Gain", "Hold", "Re-elected", "Elected", or TBD).
function senate(string $w): ?array {
    $at = strpos($w, '=== After the elections ===');
    if ($at === false) return null;
    $block = substr($w, $at + 27);
    if (preg_match('/\n==[^=]/', $block, $m, PREG_OFFSET_CAPTURE)) $block = substr($block, 0, $m[0][1]);
    $seats = [];
    foreach (explode("\n", $block) as $line) {
        if (!preg_match('/^\|(?![-}])/', $line)) continue;
        if (!preg_match('/\{\{\s*party shading\/(Democratic|Republican|Independent|TBD)(\/active)?\s*\}\}/i', $line, $p)) continue;
        if (strpos($line, '{{Sub|#}}') !== false) continue;  // the legend
        $state = preg_match('/\[\[#([^|\]]+)/', $line, $s) ? $s[1] : '';
        preg_match_all('/\{\{small\|([^{}]*)\}\}/i', $line, $r);
        $result = $r[1] ? trim(end($r[1])) : '';
        $tbd = strcasecmp($p[1], 'TBD') === 0;
        if ($tbd) $result = 'TBD';
        $seats[] = ['party' => $tbd ? 'TBD' : party($p[1]), 'up' => !empty($p[2]), 'state' => $state, 'result' => $result];
    }
    if (count($seats) !== 100) return null;
    $c = fn($f) => count(array_filter($seats, $f));
    $sum = [];
    foreach (['D', 'R', 'I'] as $k) {
        $sum[$k] = ['held' => $c(fn($x) => $x['party'] === $k && !$x['up']), 'won' => $c(fn($x) => $x['party'] === $k && $x['up'])];
    }
    $gains = [];
    foreach ($seats as $x) if ($x['up'] && $x['result'] === 'Gain') $gains[$x['party']][] = $x['state'];
    return ['parties' => $sum, 'uncalled' => array_values(array_map(fn($x) => $x['state'], array_filter($seats, fn($x) => $x['party'] === 'TBD'))),
        'gains' => $gains, 'total' => 100, 'majority' => 51,
        'races' => array_values(array_map(fn($x) => ['party' => $x['party'], 'state' => $x['state'], 'result' => $x['result']], array_filter($seats, fn($x) => $x['up'])))];
}

function counts(?array $h, string $kind): array {
    if (!$h) return [];
    if ($kind === 'house') return ['D' => $h['D'], 'R' => $h['R']];
    return ['D' => $h['parties']['D']['held'] + $h['parties']['D']['won'] + $h['parties']['I']['held'] + $h['parties']['I']['won'],
        'R' => $h['parties']['R']['held'] + $h['parties']['R']['won']];
}

function read_all(?array $last): ?array {
    $out = ['ok' => true, 'source' => 'Wikipedia', 'notes' => []];
    foreach (PAGES as $kind => $title) {
        $revs = revisions($title);
        $parse = $kind === 'house' ? 'house' : 'senate';
        $shown = null; $now = null;
        if ($revs) {
            [$cur, $stood] = $revs;
            $sw = wikitext((int) $stood[0]);
            $shown = $sw ? $parse($sw) : null;
            if ($shown) {
                $cw = $cur[0] === $stood[0] ? $sw : wikitext((int) $cur[0]);
                $now = $cw ? $parse($cw) : null;
                $a = counts($shown, $kind); $b = counts($now, $kind);
                foreach ($a as $p => $v) {
                    if ($b && $b[$p] < $v - SLACK) { $shown = null; $out['notes'][] = "$kind: the newest edit contradicts the one shown; waiting for it to settle"; break; }
                }
                if ($shown) $shown += ['revision' => $stood[0], 'as_of' => $stood[1], 'page' => 'https://en.wikipedia.org/wiki/' . $title];
            }
        }
        if (!$shown) {
            if (!$revs) $out['notes'][] = "$kind: page not read";
            $shown = $last[$kind] ?? null;  // keep the last copy we showed
            if ($shown) $shown['held_over'] = true;
        }
        $out[$kind] = $shown;
    }
    return ($out['house'] || $out['senate']) ? $out : null;
}
