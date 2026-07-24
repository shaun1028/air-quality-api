<?php
// insert.php
// Receives CO2 + PM2.5 + PM10 readings from ESP32 and inserts into Railway MySQL.
// Expected request: insert.php?co2=842.5&pm25=12.3&pm10=25.6

$host = "sakura.proxy.rlwy.net";
$port = 51259;
$dbname = "railway";
$user = "root";
$pass = "wAlJGPvJVZjhzuSNeHSWipPXsGBLNAbk";

header("Content-Type: application/json");

$conn = new mysqli($host, $user, $pass, $dbname, $port);

if ($conn->connect_error) {
    http_response_code(500);
    echo json_encode(["status" => "error", "message" => "DB connection failed: " . $conn->connect_error]);
    exit;
}

$co2  = isset($_REQUEST['co2'])  ? floatval($_REQUEST['co2'])  : null;
$pm25 = isset($_REQUEST['pm25']) ? floatval($_REQUEST['pm25']) : null;
$pm10 = isset($_REQUEST['pm10']) ? floatval($_REQUEST['pm10']) : null;

if ($co2 === null) {
    http_response_code(400);
    echo json_encode(["status" => "error", "message" => "Missing co2 parameter"]);
    $conn->close();
    exit;
}

$stmt = $conn->prepare("INSERT INTO air_quality_data (co2, pm25, pm10) VALUES (?, ?, ?)");
$stmt->bind_param("ddd", $co2, $pm25, $pm10);

if ($stmt->execute()) {
    echo json_encode(["status" => "success", "co2" => $co2, "pm25" => $pm25, "pm10" => $pm10, "id" => $conn->insert_id]);
} else {
    http_response_code(500);
    echo json_encode(["status" => "error", "message" => "Insert failed: " . $stmt->error]);
}

$stmt->close();
$conn->close();
?>
