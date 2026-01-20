// Wait for the page to finish loading
window.addEventListener("load", function() {
  // Add an event listener to the form
  document.getElementById("form").addEventListener("submit", function(event) {
    // Prevent the default form submission behavior
    event.preventDefault();

    // Read the wallet address from the form
    var walletAddress = document.getElementById("wallet_address").value;

    // Send a GET request to the Flask app
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "https://www.adventurecrypto.xyz:8000/getwalletbalance?wallet_address=" + walletAddress);
    xhr.send();

    // Handle the response from the Flask app
    xhr.onload = function() {
      if (xhr.status == 200) {
        // Parse the JSON response
        var response = JSON.parse(xhr.response);

        // Check if the response contains an error
        if (response.hasOwnProperty("error")) {
          // Show the error message
          document.getElementById("balance").innerHTML = response.error;
        } else {
          // Show the balance in Ether
          document.getElementById("balance").textContent = "Balance: " + response.balance + " Matic";
        }
      } else {
        // Show an error message
        document.getElementById("balance").innerHTML = "Error checking balance";
      }
    }
  });

  // Log a message to the console
  console.log("The page has finished loading");
});


function getBalance() {
    // Get the wallet address from the input field
    var wallet_address = document.getElementById("wallet_address").value;

    // Make an AJAX request to the Flask app
    var xhttp = new XMLHttpRequest();
    xhttp.onreadystatechange = function() {
        if (this.readyState == 4 && this.status == 200) {
            // Parse the JSON response
            var response = JSON.parse(this.responseText);

            // Check if the response contains an error
            if (response.error) {
                // Show the error message
                document.getElementById("balance").textContent = response.error;
            } else {
                // Show the balance in Ether
                document.getElementById("balance").textContent = "Balance: " + response.balance + " Matic";
            }
        }
    };
    xhttp.open("GET", "https://www.adventurecrypto.xyz:8000/getwalletbalance?wallet_address=" + wallet_address, true);
    xhttp.send();
}