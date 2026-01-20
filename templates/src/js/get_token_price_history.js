// Get the form element
const form = document.getElementById("form");

// Add a submit event listener to the form
form.addEventListener("submit", getTokenPrice);

// Define the function to get the token price
function getTokenPrice(event) {
  // Prevent the form from submitting
  event.preventDefault();

  // Get the contract address, start date, end date, and scale from the form
  const contract_address = document.getElementById("contract_address").value;
  const start_date = document.getElementById("start_date").value;
  const end_date = document.getElementById("end_date").value;
  const scale = document.getElementById("scale").value;

  // Make sure that all the required fields are filled
  if (!contract_address || !start_date || !end_date || !scale) {
    alert("Please fill all the required fields");
    return;
  }

  // Create a new XMLHttpRequest object
  const xhr = new XMLHttpRequest();

  // Open a get request to the /get_token_price endpoint
  xhr.open("GET", "/get_token_price_history?contract_address=" + contract_address + "&start_date=" + start_date + "&end_date=" + end_date + "&scale=" + scale, true);

  // Add a load event listener to the request
  xhr.addEventListener("load", handleResponse);
}

// Define the function to handle the response
function handleResponse() {
  // Parse the response as JSON
  const data = JSON.parse(this.responseText);

  // Check if there is an error in the response
  if (data.error) {
    alert(data.error);
    return;
  }

  // Get the token_price_history data from the response
  const token_price_history = data.data.token_price_history;

  // Check if there is no token_price_history data in the response
  if (!token_price_history) {
    alert("No token price history found");
    return;
  }

  // Create a new div element to display the token price data
  const div = document.createElement("div");

  // Add the token price data to the div element
  div.innerHTML = `
    <p>Contract Address: ${token_price_history[0].contract_address}</p>
    <p>Timestamp: ${token_price_history[0].timestamp}</p>
    <p>Price: ${token_price_history[0].price}</p>
    <p>Volume: ${token_price_history[0].volume}</p>
    <p>Market Cap: ${token_price_history[0].market_cap}</p>
  `;
// Append the div element to the body
document.body.appendChild(div);
}
