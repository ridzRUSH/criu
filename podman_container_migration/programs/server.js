const express = require("express");
const app = express();
let cnt = 0;

app.get("/", (req, res) => {
    cnt++;
    res.json({ cnt });
});

app.listen(8080, "0.0.0.0", () => {
    console.log("Listening on port 8080");
});
