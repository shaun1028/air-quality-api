<?php
// get_data.php
// Returns recent air quality readings from air_quality_v2 table

date_default_timezone_set('Asia/Kuala_Lumpur');

$host   = "sakura.proxy.rlwy.net";
$port   = 51259;
$dbname = "railway";
$user   = "root";
$pass   = "wAlJGPvJVZjhzuSNeHSWipPXsGBLNAbk";

header("Content-Type: application/json");
header("Access-Control-Allow-Origin: *");

$conn = new mysqli($host, $user, $pass, $dbname, $port);

if ($conn->connect_error) {
    http_response_code(500);
    echo json_encode(["status" => "error", "message" => "DB connection failed: " . $conn->connect_error]);
    exit;
}

$limit = isset($_GET['limit']) ? intval($_GET['limit']) : 100;
if ($limit <= 0 || $limit > 1000) $limit = 100;

$sql = "SELECT id, co2, pm25, pm10, temperature, humidity, timestamp 
        FROM air_quality_v2 
        ORDER BY id DESC LIMIT ?";

$stmt = $conn->prepare($sql);
$stmt->bind_param("i", $limit);
$stmt->execute();
$result = $stmt->get_result();

$rows = [];
while ($row = $result->fetch_assoc()) {
    $rows[] = $row;
}

$rows = array_reverse($rows);

echo json_encode([
    "status" => "success",
    "count"  => count($rows),
    "data"   => $rows
]);

$stmt->close();
$conn->close();
?>
